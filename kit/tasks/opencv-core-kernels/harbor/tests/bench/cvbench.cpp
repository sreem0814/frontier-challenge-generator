// cvbench: timing server and differential checker for the OpenCV core kernels of this task.
//
//   cvbench list                       timed cases: index id family rows cols tol_abs tol_rel
//   cvbench serve                      timing server on stdin/stdout (driven by collect.py)
//   cvbench check <seed> <out.bin>     run the randomized check suite, write every output to out.bin
//   cvbench cmp <a.bin> <b.bin>        compare two check/sample dumps record by record (tolerance per record)
//
// The same source is linked against three static builds of opencv_core (shipped base, candidate, optimized
// upstream). Inputs are generated from seeds chosen at grading time; every timed iteration reads its inputs
// from a row offset chosen by the per-batch nonce and has one element rewritten, so no two calls see the same
// data. Timing is measured by the caller, outside this process.
#include <opencv2/core.hpp>

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <string>
#include <vector>
#include <unistd.h>

using namespace cv;

// ------------------------------------------------------------------ random numbers
struct Rng {
    uint64_t s;
    explicit Rng(uint64_t seed) : s(seed ? seed : 0x9E3779B97F4A7C15ull) {}
    uint64_t next() {
        uint64_t z = (s += 0x9E3779B97F4A7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    double uni() { return (double)(next() >> 11) * (1.0 / 9007199254740992.0); }
    int below(int n) { return n <= 1 ? 0 : (int)(next() % (uint64_t)n); }
};

static double depthMin(int d) {
    switch (d) {
    case CV_8U: return 0; case CV_8S: return -128; case CV_16U: return 0; case CV_16S: return -32768;
    case CV_32S: return -2147483648.0; case CV_32U: return 0; default: return -1e300;
    }
}
static double depthMax(int d) {
    switch (d) {
    case CV_8U: return 255; case CV_8S: return 127; case CV_16U: return 65535; case CV_16S: return 32767;
    case CV_32S: return 2147483647.0; case CV_32U: return 4294967295.0; default: return 1e300;
    }
}

static void setElem(uchar* p, int depth, double v) {
    switch (depth) {
    case CV_8U: *p = saturate_cast<uchar>(v); break;
    case CV_8S: *(schar*)p = saturate_cast<schar>(v); break;
    case CV_16U: *(ushort*)p = saturate_cast<ushort>(v); break;
    case CV_16S: *(short*)p = saturate_cast<short>(v); break;
    case CV_32S: *(int*)p = saturate_cast<int>(v); break;
    case CV_32U: *(unsigned*)p = saturate_cast<unsigned>(v); break;
    case CV_32F: *(float*)p = (float)v; break;
    case CV_64F: *(double*)p = v; break;
    case CV_16F: *(hfloat*)p = hfloat((float)v); break;
    default: CV_Error(Error::StsBadArg, "depth");
    }
}
static double getElem(const uchar* p, int depth) {
    switch (depth) {
    case CV_8U: return *p;
    case CV_8S: return *(const schar*)p;
    case CV_16U: return *(const ushort*)p;
    case CV_16S: return *(const short*)p;
    case CV_32S: return *(const int*)p;
    case CV_32U: return *(const unsigned*)p;
    case CV_32F: return *(const float*)p;
    case CV_64F: return *(const double*)p;
    case CV_16F: return (float)*(const hfloat*)p;
    case CV_Bool: return *p;
    default: return 0;
    }
}

// Random value in [lo, hi]; integer depths draw integers. A few special values (range ends) appear on purpose.
static double drawValue(Rng& r, int depth, double lo, double hi) {
    lo = std::max(lo, depthMin(depth));
    hi = std::min(hi, depthMax(depth));
    const bool isInt = depth != CV_32F && depth != CV_64F && depth != CV_16F;
    if ((r.next() & 63) == 0) return (r.next() & 1) ? lo : hi;
    double v = lo + (hi - lo) * r.uni();
    return isInt ? std::floor(v + 0.5) : v;
}

static void fillRandom(Mat& m, Rng& r, double lo, double hi) {
    const int depth = m.depth();
    const size_t es1 = CV_ELEM_SIZE1(m.type());
    for (int y = 0; y < m.rows; y++) {
        uchar* row = m.ptr(y);
        const size_t n = (size_t)m.cols * m.channels();
        for (size_t i = 0; i < n; i++) setElem(row + i * es1, depth, drawValue(r, depth, lo, hi));
    }
}

static void fillMask(Mat& m, Rng& r) {
    for (int y = 0; y < m.rows; y++) {
        uchar* row = m.ptr<uchar>(y);
        for (int x = 0; x < m.cols; x++) row[x] = (r.next() % 3) ? (uchar)(1 + r.below(255)) : 0;
    }
}

// ------------------------------------------------------------------ timed cases
struct Arg {
    int type;       // CV_MAKETYPE
    double lo, hi;  // value range
};
typedef std::function<void(std::vector<Mat>& in, Mat& mask, std::vector<Mat>& out)> KernelFn;
struct Case {
    const char* id;
    const char* family;
    int rows, cols;
    std::vector<Arg> args;
    bool useMask;
    double tolAbs, tolRel;  // allowed difference from the shipped implementation (see cmp)
    KernelFn fn;
    double tolNorm = 0;
};

static Mat scalarOut(std::vector<Mat>& out, int n) {
    if (out.empty()) out.resize(1);
    out[0].create(1, n, CV_64F);
    return out[0];
}
static void putScalar(std::vector<Mat>& out, const Scalar& s) {
    Mat o = scalarOut(out, 4);
    for (int i = 0; i < 4; i++) o.at<double>(i) = s[i];
}
static void putDouble(std::vector<Mat>& out, double v) {
    Mat o = scalarOut(out, 1);
    o.at<double>(0) = v;
}
static Mat& out0(std::vector<Mat>& out) { if (out.empty()) out.resize(1); return out[0]; }

#define K [](std::vector<Mat>& in, Mat& mask, std::vector<Mat>& out)
#define UNUSED_MASK (void)mask

static const double I8 = 255, F = 1000;

static std::vector<Case> makeCases() {
    std::vector<Case> c;
    const int R = 480, C = 640;   // VGA frame
    const int R2 = 720, C2 = 1280; // 720p frame
    const int RO = 479, CO = 637;  // odd sizes: vector tails everywhere
    // ---- arithmetic: add / subtract
    c.push_back({"add_8uC1", "arith", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; add(in[0], in[1], out0(out)); }});
    c.push_back({"add_16sC1", "arith", R, C, {{CV_16SC1, -32768, 32767}, {CV_16SC1, -32768, 32767}}, false, 0, 0,
                 K { UNUSED_MASK; add(in[0], in[1], out0(out)); }});
    c.push_back({"add_32fC1", "arith", R2, C2, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; add(in[0], in[1], out0(out)); }});
    c.push_back({"sub_8uC3", "arith", RO, CO, {{CV_8UC3, 0, I8}, {CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; subtract(in[0], in[1], out0(out)); }});
    c.push_back({"add_8u16s", "arith", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; add(in[0], in[1], out0(out), noArray(), CV_16S); }});
    c.push_back({"addS_32fC3", "arith", R, C, {{CV_32FC3, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; add(in[0], Scalar(1.5, -2.25, 100.125), out0(out)); }});
    c.push_back({"sub_16uC1_mask", "arith", R, C, {{CV_16UC1, 0, 65535}, {CV_16UC1, 0, 65535}}, true, 0, 0,
                 K { Mat& o = out0(out); if (o.empty()) { o.create(in[0].size(), in[0].type()); o.setTo(0); } subtract(in[0], in[1], o, mask); }});
    // ---- multiply / divide
    c.push_back({"mul_8uC1", "muldiv", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; multiply(in[0], in[1], out0(out)); }});
    c.push_back({"mul_16sC1_scale", "muldiv", R, C, {{CV_16SC1, -2000, 2000}, {CV_16SC1, -2000, 2000}}, false, 1, 0,
                 K { UNUSED_MASK; multiply(in[0], in[1], out0(out), 0.125); }});
    c.push_back({"mul_32fC1", "muldiv", R2, C2, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; multiply(in[0], in[1], out0(out)); }});
    c.push_back({"div_8uC1", "muldiv", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 1, 0,
                 K { UNUSED_MASK; divide(in[0], in[1], out0(out)); }});
    c.push_back({"div_16sC1_scale", "muldiv", R, C, {{CV_16SC1, -32768, 32767}, {CV_16SC1, -300, 300}}, false, 1, 0,
                 K { UNUSED_MASK; divide(in[0], in[1], out0(out), 3.0); }});
    c.push_back({"div_32fC1", "muldiv", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, 1, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; divide(in[0], in[1], out0(out)); }});
    c.push_back({"recip_32fC1", "muldiv", R, C, {{CV_32FC1, 1, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; divide(2.5, in[0], out0(out)); }});
    // ---- absdiff / min / max
    c.push_back({"absdiff_8uC1", "absminmax", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; absdiff(in[0], in[1], out0(out)); }});
    c.push_back({"absdiff_16sC1", "absminmax", R, C, {{CV_16SC1, -32768, 32767}, {CV_16SC1, -32768, 32767}}, false, 0, 0,
                 K { UNUSED_MASK; absdiff(in[0], in[1], out0(out)); }});
    c.push_back({"absdiff_32fC1", "absminmax", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; absdiff(in[0], in[1], out0(out)); }});
    c.push_back({"absdiffS_8uC3", "absminmax", RO, CO, {{CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; absdiff(in[0], Scalar(17, 128, 250), out0(out)); }});
    c.push_back({"min_16uC1", "absminmax", R, C, {{CV_16UC1, 0, 65535}, {CV_16UC1, 0, 65535}}, false, 0, 0,
                 K { UNUSED_MASK; min(in[0], in[1], out0(out)); }});
    c.push_back({"max_32fC1", "absminmax", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; max(in[0], in[1], out0(out)); }});
    // ---- weighted sums
    c.push_back({"addWeighted_8uC1", "weighted", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 1, 0,
                 K { UNUSED_MASK; addWeighted(in[0], 0.3, in[1], 0.7, 2.5, out0(out)); }});
    c.push_back({"addWeighted_16sC1", "weighted", R, C, {{CV_16SC1, -32768, 32767}, {CV_16SC1, -32768, 32767}}, false, 1, 0,
                 K { UNUSED_MASK; addWeighted(in[0], 0.75, in[1], -0.5, -3, out0(out)); }});
    c.push_back({"addWeighted_32fC1", "weighted", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; addWeighted(in[0], 0.3, in[1], 0.7, 2.5, out0(out)); }, 1e-6});
    c.push_back({"scaleAdd_32fC1", "weighted", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; scaleAdd(in[0], 1.75, in[1], out0(out)); }, 1e-6});
    c.push_back({"addWeighted_8uC3_odd", "weighted", RO, CO, {{CV_8UC3, 0, I8}, {CV_8UC3, 0, I8}}, false, 1, 0,
                 K { UNUSED_MASK; addWeighted(in[0], 0.5, in[1], 0.5, 0, out0(out)); }});
    // ---- compare / range / bitwise
    c.push_back({"cmpGT_8uC1", "compare", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; compare(in[0], in[1], out0(out), CMP_GT); }});
    c.push_back({"cmpEQ_16sC1", "compare", R, C, {{CV_16SC1, -20, 20}, {CV_16SC1, -20, 20}}, false, 0, 0,
                 K { UNUSED_MASK; compare(in[0], in[1], out0(out), CMP_EQ); }});
    c.push_back({"cmpLE_32fC1", "compare", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; compare(in[0], in[1], out0(out), CMP_LE); }});
    c.push_back({"inRange_8uC3", "compare", R, C, {{CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; inRange(in[0], Scalar(20, 50, 90), Scalar(200, 180, 250), out0(out)); }});
    c.push_back({"inRange_32fC1", "compare", R, C, {{CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; inRange(in[0], Scalar(-250.5), Scalar(400.25), out0(out)); }});
    c.push_back({"and_8uC1_mask", "compare", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, true, 0, 0,
                 K { Mat& o = out0(out); if (o.empty()) { o.create(in[0].size(), in[0].type()); o.setTo(0); } bitwise_and(in[0], in[1], o, mask); }});
    // ---- conversions
    c.push_back({"cvt_8u32f", "convert", R, C, {{CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_32F); }});
    c.push_back({"cvt_32f8u", "convert", R, C, {{CV_32FC1, -50, 300}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_8U); }});
    c.push_back({"cvt_16s8u", "convert", R, C, {{CV_16SC1, -400, 400}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_8U); }});
    c.push_back({"cvt_8u16s_scale", "convert", R, C, {{CV_8UC3, 0, I8}}, false, 1, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_16S, 2.0, -100.0); }});
    c.push_back({"cvt_32f16s_scale", "convert", R, C, {{CV_32FC1, -F, F}}, false, 1, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_16S, 30.0, 0.5); }});
    c.push_back({"cvt_16u32f_scale", "convert", R, C, {{CV_16UC1, 0, 65535}}, false, 0, 1e-6,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_32F, 1.0 / 65535.0); }, 1e-6});
    c.push_back({"cvt_32f64f", "convert", R, C, {{CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_64F); }});
    c.push_back({"cvt_64f32s", "convert", R, C, {{CV_64FC1, -1e6, 1e6}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_32S); }});
    c.push_back({"cvt_32f16f", "convert", R, C, {{CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_16F); }});
    c.push_back({"cvt_16f32f", "convert", R, C, {{CV_16FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_32F); }});
    c.push_back({"cvt_8u8u_scale", "convert", RO, CO, {{CV_8UC1, 0, I8}}, false, 1, 0,
                 K { UNUSED_MASK; in[0].convertTo(out0(out), CV_8U, 1.5, -20.0); }});
    c.push_back({"cvtAbs_16s8u", "convert", R, C, {{CV_16SC1, -32768, 32767}}, false, 1, 0,
                 K { UNUSED_MASK; convertScaleAbs(in[0], out0(out), 0.25, 3); }});
    c.push_back({"cvtAbs_32f8u", "convert", R, C, {{CV_32FC1, -F, F}}, false, 1, 0,
                 K { UNUSED_MASK; convertScaleAbs(in[0], out0(out), 0.5, 0); }});
    // ---- lookup tables
    c.push_back({"lut_8uC1", "lut", R2, C2, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; LUT(in[0], in[1].row(0).colRange(0, 256), out0(out)); }});
    c.push_back({"lut_8uC3", "lut", R, C, {{CV_8UC3, 0, I8}, {CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; LUT(in[0], in[1].row(0).colRange(0, 256), out0(out)); }});
    c.push_back({"lut_8u32f", "lut", R, C, {{CV_8UC1, 0, I8}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; LUT(in[0], in[1].row(0).colRange(0, 256), out0(out)); }});
    c.push_back({"lut_8u16s_C4", "lut", R, C, {{CV_8UC4, 0, I8}, {CV_16SC1, -32768, 32767}}, false, 0, 0,
                 K { UNUSED_MASK; LUT(in[0], in[1].row(0).colRange(0, 256), out0(out)); }});
    // ---- sums and means
    c.push_back({"sum_8uC1", "sum", R2, C2, {{CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; putScalar(out, sum(in[0])); }});
    c.push_back({"sum_16sC3", "sum", R, C, {{CV_16SC3, -32768, 32767}}, false, 0, 0,
                 K { UNUSED_MASK; putScalar(out, sum(in[0])); }});
    c.push_back({"sum_32fC1", "sum", R, C, {{CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; putScalar(out, sum(in[0])); }});
    c.push_back({"mean_8uC1_mask", "sum", R, C, {{CV_8UC1, 0, I8}}, true, 0, 1e-9,
                 K { putScalar(out, mean(in[0], mask)); }});
    c.push_back({"meanStdDev_8uC3", "sum", R, C, {{CV_8UC3, 0, I8}}, false, 0, 1e-9,
                 K { UNUSED_MASK; Scalar m, s; meanStdDev(in[0], m, s); Mat o = scalarOut(out, 6);
                     for (int i = 0; i < 3; i++) { o.at<double>(i) = m[i]; o.at<double>(3 + i) = s[i]; } }});
    c.push_back({"meanStdDev_32fC1", "sum", R, C, {{CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; Scalar m, s; meanStdDev(in[0], m, s); Mat o = scalarOut(out, 2);
                     o.at<double>(0) = m[0]; o.at<double>(1) = s[0]; }});
    // ---- norms
    c.push_back({"normL2_8uC1", "norm", R2, C2, {{CV_8UC1, 0, I8}}, false, 0, 1e-12,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], NORM_L2)); }});
    c.push_back({"normL1_32fC1", "norm", R, C, {{CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], NORM_L1)); }});
    c.push_back({"normInf_16sC1", "norm", R, C, {{CV_16SC1, -32768, 32767}}, false, 0, 0,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], NORM_INF)); }});
    c.push_back({"normL2_32fC1", "norm", R, C, {{CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], NORM_L2)); }});
    c.push_back({"normDiffL2_8uC1", "norm", R, C, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 1e-12,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], in[1], NORM_L2)); }});
    c.push_back({"normDiffL1_8uC3", "norm", RO, CO, {{CV_8UC3, 0, I8}, {CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], in[1], NORM_L1)); }});
    c.push_back({"normL1_8uC1_mask", "norm", R, C, {{CV_8UC1, 0, I8}}, true, 0, 0,
                 K { putDouble(out, norm(in[0], NORM_L1, mask)); }});
    c.push_back({"normDiffInf_32fC1", "norm", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; putDouble(out, norm(in[0], in[1], NORM_INF)); }});
    // ---- counting and extrema
    c.push_back({"countNZ_8uC1", "minmax", R2, C2, {{CV_8UC1, 0, 3}}, false, 0, 0,
                 K { UNUSED_MASK; putDouble(out, countNonZero(in[0])); }});
    c.push_back({"countNZ_32fC1", "minmax", R, C, {{CV_32FC1, -1, 1}}, false, 0, 0,
                 K { UNUSED_MASK; putDouble(out, countNonZero(in[0])); }});
    c.push_back({"minMaxLoc_8uC1", "minmax", R, C, {{CV_8UC1, 5, 250}}, false, 0, 0,
                 K { UNUSED_MASK; double mn, mx; Point a, b; minMaxLoc(in[0], &mn, &mx, &a, &b); Mat o = scalarOut(out, 6);
                     o.at<double>(0) = mn; o.at<double>(1) = mx; o.at<double>(2) = a.x; o.at<double>(3) = a.y;
                     o.at<double>(4) = b.x; o.at<double>(5) = b.y; }});
    c.push_back({"minMaxLoc_32fC1", "minmax", R, C, {{CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; double mn, mx; Point a, b; minMaxLoc(in[0], &mn, &mx, &a, &b); Mat o = scalarOut(out, 6);
                     o.at<double>(0) = mn; o.at<double>(1) = mx; o.at<double>(2) = a.x; o.at<double>(3) = a.y;
                     o.at<double>(4) = b.x; o.at<double>(5) = b.y; }});
    c.push_back({"minMaxIdx_16sC1_mask", "minmax", R, C, {{CV_16SC1, -30000, 30000}}, true, 0, 0,
                 K { double mn, mx; int a[2], b[2]; minMaxIdx(in[0], &mn, &mx, a, b, mask); Mat o = scalarOut(out, 6);
                     o.at<double>(0) = mn; o.at<double>(1) = mx; o.at<double>(2) = a[0]; o.at<double>(3) = a[1];
                     o.at<double>(4) = b[0]; o.at<double>(5) = b[1]; }});
    // ---- channels
    c.push_back({"split_8uC3", "channels", R2, C2, {{CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; out.resize(3); split(in[0], out); }});
    c.push_back({"merge_8uC3", "channels", R2, C2, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; std::vector<Mat> v(in.begin(), in.begin() + 3); merge(v, out0(out)); }});
    c.push_back({"split_32fC4", "channels", R, C, {{CV_32FC4, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; out.resize(4); split(in[0], out); }});
    c.push_back({"merge_16uC4", "channels", R, C, {{CV_16UC1, 0, 65535}, {CV_16UC1, 0, 65535}, {CV_16UC1, 0, 65535}, {CV_16UC1, 0, 65535}}, false, 0, 0,
                 K { UNUSED_MASK; std::vector<Mat> v(in.begin(), in.begin() + 4); merge(v, out0(out)); }});
    // ---- math functions
    c.push_back({"magnitude_32f", "mathfn", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 0, 1e-6,
                 K { UNUSED_MASK; magnitude(in[0], in[1], out0(out)); }});
    c.push_back({"phase_32f", "mathfn", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 2e-4, 0,
                 K { UNUSED_MASK; phase(in[0], in[1], out0(out)); }});
    c.push_back({"cartToPolar_32f_deg", "mathfn", R, C, {{CV_32FC1, -F, F}, {CV_32FC1, -F, F}}, false, 1e-2, 1e-6,
                 K { UNUSED_MASK; out.resize(2); cartToPolar(in[0], in[1], out[0], out[1], true); }});
    c.push_back({"polarToCart_32f", "mathfn", R, C, {{CV_32FC1, 0, F}, {CV_32FC1, -6.3, 6.3}}, false, 1e-3, 1e-5,
                 K { UNUSED_MASK; out.resize(2); polarToCart(in[0], in[1], out[0], out[1]); }});
    c.push_back({"exp_32f", "mathfn", R, C, {{CV_32FC1, -80, 80}}, false, 0, 1e-6,
                 K { UNUSED_MASK; exp(in[0], out0(out)); }});
    c.push_back({"log_32f", "mathfn", R, C, {{CV_32FC1, 1e-3, 1e6}}, false, 1e-6, 1e-6,
                 K { UNUSED_MASK; log(in[0], out0(out)); }});
    c.push_back({"exp_64f", "mathfn", R, C, {{CV_64FC1, -300, 300}}, false, 0, 1e-14,
                 K { UNUSED_MASK; exp(in[0], out0(out)); }});
    c.push_back({"sqrt_32f", "mathfn", R, C, {{CV_32FC1, 0, F}}, false, 0, 1e-7,
                 K { UNUSED_MASK; sqrt(in[0], out0(out)); }});
    c.push_back({"pow_32f_2_5", "mathfn", R, C, {{CV_32FC1, 0, 100}}, false, 0, 4e-6,
                 K { UNUSED_MASK; pow(in[0], 2.5, out0(out)); }});
    // ---- matrix products and transforms
    c.push_back({"gemm_32f_256", "matmul", 256, 256, {{CV_32FC1, -1, 1}, {CV_32FC1, -1, 1}}, false, 1e-5, 1e-4,
                 K { UNUSED_MASK; gemm(in[0], in[1], 1.0, noArray(), 0.0, out0(out)); }, 1e-5});
    c.push_back({"gemm_64f_128_tAB", "matmul", 128, 128, {{CV_64FC1, -1, 1}, {CV_64FC1, -1, 1}, {CV_64FC1, -1, 1}}, false, 1e-12, 1e-10,
                 K { UNUSED_MASK; gemm(in[0], in[1], 0.5, in[2], 2.0, out0(out), GEMM_1_T); }, 1e-12});
    c.push_back({"mulTransposed_32f", "matmul", 64, 4096, {{CV_32FC1, -1, 1}}, false, 1e-5, 1e-4,
                 K { UNUSED_MASK; mulTransposed(in[0], out0(out), false); }, 1e-5});
    c.push_back({"dot_32fC1", "matmul", R, C, {{CV_32FC1, -10, 10}, {CV_32FC1, -10, 10}}, false, 0, 1e-6,
                 K { UNUSED_MASK; putDouble(out, in[0].dot(in[1])); }});
    c.push_back({"dot_8uC1", "matmul", R2, C2, {{CV_8UC1, 0, I8}, {CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; putDouble(out, in[0].dot(in[1])); }});
    c.push_back({"transform_8uC3", "matmul", R, C, {{CV_8UC3, 0, I8}}, false, 1, 0,
                 K { UNUSED_MASK; Matx33f m(0.299f, 0.587f, 0.114f, -0.169f, -0.331f, 0.5f, 0.5f, -0.419f, -0.081f);
                     transform(in[0], out0(out), m); }});
    c.push_back({"transform_32fC3_3x4", "matmul", R, C, {{CV_32FC3, -F, F}}, false, 0, 1e-5,
                 K { UNUSED_MASK; Matx34f m(0.9f, 0.1f, -0.2f, 3.f, 0.05f, 1.1f, 0.3f, -7.f, -0.4f, 0.2f, 0.8f, 1.f);
                     transform(in[0], out0(out), m); }, 1e-6});
    c.push_back({"perspective_32fC2", "matmul", 1, 307200, {{CV_32FC2, -F, F}}, false, 0, 1e-5,
                 K { UNUSED_MASK; Matx33d m(1.01, 0.02, 3.0, -0.01, 0.98, -2.0, 1e-5, 2e-5, 1.0);
                     perspectiveTransform(in[0], out0(out), m); }});
    // ---- reductions along an axis
    c.push_back({"reduceRowSum_8u32s", "reduce", R, C, {{CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; reduce(in[0], out0(out), 0, REDUCE_SUM, CV_32S); }});
    c.push_back({"reduceColSum_32f", "reduce", R, C, {{CV_32FC1, -F, F}}, false, 0, 1e-5,
                 K { UNUSED_MASK; reduce(in[0], out0(out), 1, REDUCE_SUM, CV_32F); }, 1e-5});
    c.push_back({"reduceRowMax_32f", "reduce", R, C, {{CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; reduce(in[0], out0(out), 0, REDUCE_MAX); }});
    c.push_back({"reduceColAvg_8uC3", "reduce", R, C, {{CV_8UC3, 0, I8}}, false, 0, 1e-9,
                 K { UNUSED_MASK; reduce(in[0], out0(out), 1, REDUCE_AVG, CV_64F); }});
    // ---- copies
    c.push_back({"transpose_8uC1", "copy", R, C, {{CV_8UC1, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; transpose(in[0], out0(out)); }});
    c.push_back({"transpose_32fC1", "copy", R, C, {{CV_32FC1, -F, F}}, false, 0, 0,
                 K { UNUSED_MASK; transpose(in[0], out0(out)); }});
    c.push_back({"flipXY_8uC3", "copy", R, C, {{CV_8UC3, 0, I8}}, false, 0, 0,
                 K { UNUSED_MASK; flip(in[0], out0(out), -1); }});
    c.push_back({"flipY_16uC1", "copy", R, C, {{CV_16UC1, 0, 65535}}, false, 0, 0,
                 K { UNUSED_MASK; flip(in[0], out0(out), 1); }});
    return c;
}

// ------------------------------------------------------------------ timing server
static const int PAD = 64;   // extra rows in every input pool; each iteration reads rows [off, off + rows)

struct Prepared {
    int idx = -1;
    std::vector<Mat> pool;   // (rows + PAD) x cols per input
    Mat maskPool;
    std::vector<Mat> in;     // current views
    Mat mask;
    std::vector<Mat> out;
    std::vector<double> samples;
};

static void sampleOutputs(std::vector<Mat>& out, Rng& r, std::vector<double>& samples) {
    for (Mat& o : out) {
        const size_t n = o.total() * o.channels();
        if (!n) { samples.push_back(NAN); continue; }
        const size_t es1 = CV_ELEM_SIZE1(o.type());
        for (int k = 0; k < 4; k++) {
            size_t e = (size_t)(r.next() % n);
            size_t perRow = (size_t)o.cols * o.channels();
            const uchar* p = o.ptr((int)(e / perRow)) + (e % perRow) * es1;
            samples.push_back(getElem(p, o.depth()));
        }
    }
}

static bool writeAll(int fd, const void* p, size_t n) {
    const char* c = (const char*)p;
    while (n) {
        ssize_t w = ::write(fd, c, n);
        if (w < 0) { if (errno == EINTR) continue; return false; }
        c += w; n -= (size_t)w;
    }
    return true;
}

// Record format (little endian): u32 magic 'CVBR', u32 idlen, id bytes, u32 depth, u64 count, f64 tolAbs, f64 tolRel,
// f64 tolNorm, then count values as f64 (outputs are widened to double so one comparator serves every depth).
static void writeRecord(FILE* f, const std::string& id, int depth, const std::vector<double>& vals, double ta, double tr,
                        double tn = 0) {
    uint32_t magic = 0x52425643u, idlen = (uint32_t)id.size(), d = (uint32_t)depth;
    uint64_t n = vals.size();
    fwrite(&magic, 4, 1, f); fwrite(&idlen, 4, 1, f); fwrite(id.data(), 1, idlen, f); fwrite(&d, 4, 1, f);
    fwrite(&n, 8, 1, f); fwrite(&ta, 8, 1, f); fwrite(&tr, 8, 1, f); fwrite(&tn, 8, 1, f);
    if (n) fwrite(vals.data(), 8, n, f);
}
static void matValues(const Mat& o, std::vector<double>& v) {
    v.clear();
    const size_t es1 = CV_ELEM_SIZE1(o.type());
    for (int y = 0; y < o.rows; y++) {
        const uchar* row = o.ptr(y);
        const size_t n = (size_t)o.cols * o.channels();
        for (size_t i = 0; i < n; i++) v.push_back(getElem(row + i * es1, o.depth()));
    }
}

static int serve() {
    std::vector<Case> cases = makeCases();
    Prepared P;
    char line[512];
    setvbuf(stdin, nullptr, _IOLBF, 0);
    while (fgets(line, sizeof line, stdin)) {
        char cmd = line[0];
        char reply[256];
        if (cmd == 'P') {                       // P <case index> <seed>
            int idx; unsigned long long seed;
            if (sscanf(line + 1, "%d %llu", &idx, &seed) != 2 || idx < 0 || idx >= (int)cases.size()) return 2;
            CV_Assert(cases[idx].args.size() <= 4);
            const Case& cs = cases[idx];
            P = Prepared(); P.idx = idx;
            Rng r(seed);
            for (const Arg& a : cs.args) {
                Mat m(cs.rows + PAD, cs.cols, a.type);
                fillRandom(m, r, a.lo, a.hi);
                P.pool.push_back(m);
            }
            if (cs.useMask) { P.maskPool.create(cs.rows + PAD, cs.cols, CV_8UC1); fillMask(P.maskPool, r); }
            snprintf(reply, sizeof reply, "OK P %d\n", idx);
        } else if (cmd == 'T') {                // T <iters> <nonce>
            int iters; unsigned long long nonce;
            if (sscanf(line + 1, "%d %llu", &iters, &nonce) != 2 || P.idx < 0) return 2;
            const Case& cs = cases[P.idx];
            Rng r(nonce);
            P.samples.clear();
            P.in.resize(P.pool.size());
            // every batch starts from the same state: zeroed outputs (masked ops keep unmasked pixels), and the
            // input pools are restored after each call, so a batch depends only on (case, seed, iters, nonce)
            for (Mat& o : P.out)
                for (int y = 0; y < o.rows; y++) memset(o.ptr(y), 0, (size_t)o.cols * o.elemSize());
            uchar* touched[4]; uint64_t saved[4];
            for (int it = 0; it < iters; it++) {
                const int off = r.below(PAD + 1);
                for (size_t i = 0; i < P.pool.size(); i++) {
                    P.in[i] = P.pool[i].rowRange(off, off + cs.rows);
                    Mat& m = P.in[i];
                    const int y = r.below(m.rows), x = r.below(m.cols * m.channels());
                    touched[i] = m.ptr(y) + (size_t)x * CV_ELEM_SIZE1(m.type());
                    memcpy(&saved[i], touched[i], CV_ELEM_SIZE1(m.type()));
                    setElem(touched[i], m.depth(), drawValue(r, m.depth(), cs.args[i].lo, cs.args[i].hi));
                }
                if (cs.useMask) P.mask = P.maskPool.rowRange(off, off + cs.rows);
                cs.fn(P.in, P.mask, P.out);
                sampleOutputs(P.out, r, P.samples);
                for (size_t i = P.pool.size(); i-- > 0;)
                    memcpy(touched[i], &saved[i], CV_ELEM_SIZE1(P.in[i].type()));
            }
            snprintf(reply, sizeof reply, "D %llu\n", nonce);
        } else if (cmd == 'S') {                // S <path> [samples]: samples (+ full last outputs)
            char path[400], what[32] = "";
            if (sscanf(line + 1, "%399s %31s", path, what) < 1 || P.idx < 0) return 2;
            const bool samplesOnly = !strcmp(what, "samples");
            const Case& cs = cases[P.idx];
            FILE* f = fopen(path, "wb");
            if (!f) return 3;
            writeRecord(f, std::string(cs.id) + "#samples", CV_64F, P.samples, cs.tolAbs, cs.tolRel, cs.tolNorm);
            std::vector<double> v;
            for (size_t i = 0; !samplesOnly && i < P.out.size(); i++) {
                matValues(P.out[i], v);
                writeRecord(f, std::string(cs.id) + "#out" + std::to_string(i), P.out[i].depth(), v, cs.tolAbs, cs.tolRel, cs.tolNorm);
            }
            fclose(f);
            snprintf(reply, sizeof reply, "OK S\n");
        } else if (cmd == 'Q') {
            return 0;
        } else {
            return 2;
        }
        if (!writeAll(1, reply, strlen(reply))) return 4;
    }
    return 0;
}

// ------------------------------------------------------------------ randomized check suite
// Broader than the timed cases: every depth/channel combination of the timed functions, odd and tiny sizes,
// non-continuous views, masks, scalars and in-place calls. Outputs go to a dump for `cmp`.
struct CheckCtx {
    Rng r;
    FILE* f;
    int n = 0;
    explicit CheckCtx(uint64_t s, FILE* ff) : r(s), f(ff) {}
};

static Size pickSize(Rng& r) {
    static const Size sizes[] = {{1, 1}, {3, 1}, {1, 5}, {7, 3}, {17, 2}, {31, 9}, {33, 33}, {64, 16}, {127, 5},
                                 {255, 3}, {129, 65}, {640, 2}, {97, 61}, {200, 37}};
    return sizes[r.below((int)(sizeof sizes / sizeof sizes[0]))];
}
// A random matrix, continuous or a view into a larger one.
static Mat randMat(Rng& r, Size sz, int type, double lo, double hi, bool view) {
    if (!view) { Mat m(sz, type); fillRandom(m, r, lo, hi); return m; }
    Mat big(sz.height + 3, sz.width + 5, type);
    fillRandom(big, r, lo, hi);
    return big(Rect(2, 1, sz.width, sz.height));
}
static void emitMat(CheckCtx& cx, const std::string& id, const Mat& m, double ta, double tr, double tn = 0) {
    std::vector<double> v;
    matValues(m, v);
    writeRecord(cx.f, id, m.depth(), v, ta, tr, tn);
    cx.n++;
}
static void emitVals(CheckCtx& cx, const std::string& id, const std::vector<double>& v, double ta, double tr) {
    writeRecord(cx.f, id, CV_64F, v, ta, tr);
    cx.n++;
}
static void rangeOf(int depth, double& lo, double& hi) {
    switch (depth) {
    case CV_8U: lo = 0; hi = 255; break;
    case CV_8S: lo = -128; hi = 127; break;
    case CV_16U: lo = 0; hi = 65535; break;
    case CV_16S: lo = -32768; hi = 32767; break;
    case CV_32S: lo = -2147483648.0; hi = 2147483647.0; break;
    case CV_16F: lo = -1000; hi = 1000; break;
    default: lo = -1e4; hi = 1e4;
    }
}
static const char* dn(int d) {
    static const char* names[] = {"8u", "8s", "16u", "16s", "32s", "32f", "64f", "16f", "16bf", "bool", "64u", "64s", "32u"};
    return d >= 0 && d < 13 ? names[d] : "?";
}

// Float tolerances of the check suite (relative unless stated); integer outputs must match exactly.
static double fltTol(int depth, double rel32, double rel64) { return depth == CV_64F ? rel64 : depth == CV_32F || depth == CV_16F ? rel32 : 0; }

static void emitExc(CheckCtx& cx, const std::string& id) {
    std::vector<double> v;
    writeRecord(cx.f, id + "#exception", 255, v, 0, 0);
    cx.n++;
}
// E: run CALL (which leaves its result in `o`) and record o; an OpenCV exception is recorded as such, so a
// call that the shipped build rejects must be rejected the same way.
#define E3(ID, CALL, TA, TR, TN) do { try { CALL; emitMat(cx, ID, o, TA, TR, TN); } catch (const cv::Exception&) { emitExc(cx, ID); } } while (0)
#define E(ID, CALL, TA, TR) E3(ID, CALL, TA, TR, 0)
#define V(ID, TA, TR, ...) do { std::vector<double> v; try { __VA_ARGS__; emitVals(cx, ID, v, TA, TR); } catch (const cv::Exception&) { emitExc(cx, ID); } } while (0)

static void runChecks(CheckCtx& cx, int rounds) {
    Rng& r = cx.r;
    const int depths[] = {CV_8U, CV_8S, CV_16U, CV_16S, CV_32S, CV_32F, CV_64F};
    const int cns[] = {1, 2, 3, 4};
    for (int round = 0; round < rounds; round++) {
        for (int d : depths) {
            for (int cn : cns) {
                if (r.below(4) && cn != 1 && cn != 3) continue;
                Size sz = pickSize(r);
                const bool view = r.below(2) == 0;
                double lo, hi; rangeOf(d, lo, hi);
                const int t = CV_MAKETYPE(d, cn);
                const std::string tag = std::string(dn(d)) + "C" + std::to_string(cn) + "_" + std::to_string(sz.width) + "x" +
                                  std::to_string(sz.height) + (view ? "v" : "") + "_r" + std::to_string(round);
                Mat a = randMat(r, sz, t, lo, hi, view), b = randMat(r, sz, t, lo, hi, view);
                Mat mask(sz, CV_8U); fillMask(mask, r);
                Scalar s(drawValue(r, d, lo, hi), drawValue(r, d, lo, hi), drawValue(r, d, lo, hi), drawValue(r, d, lo, hi));
                const double ft = fltTol(d, 1e-6, 1e-14);
                const double it = d >= CV_32F ? 0 : 1;   // integer outputs of scaled ops: off by one allowed
                Mat o;
                E("add_" + tag, add(a, b, o), 0, 0);
                E("sub_" + tag, subtract(a, b, o), 0, 0);
                E("addS_" + tag, add(a, s, o), 0, 0);
                E("subRS_" + tag, subtract(s, a, o), 0, 0);
                E("addM_" + tag, (o = Mat::zeros(sz, t), add(a, b, o, mask)), 0, 0);
                E("subM_" + tag, (o = Mat::zeros(sz, t), subtract(a, s, o, mask)), 0, 0);
                E("addW_" + tag, add(a, b, o, noArray(), d == CV_64F ? CV_64F : CV_32F), 0, 0);
                E("addW16s_" + tag, add(a, b, o, noArray(), CV_16S), 0, 0);
                E("mul_" + tag, multiply(a, b, o), 0, ft);
                E("mulSc_" + tag, multiply(a, b, o, 1.0 / 3), it, ft);
                E("mulW32f_" + tag, multiply(a, b, o, 0.25, CV_32F), 0, 1e-6);
                E("div_" + tag, divide(a, b, o), it, ft);
                E("divSc_" + tag, divide(a, b, o, 7.5), it, ft);
                E("recip_" + tag, divide(3.0, b, o), it, ft);
                E("absdiff_" + tag, absdiff(a, b, o), 0, 0);
                E("absdiffS_" + tag, absdiff(a, s, o), 0, 0);
                E("min_" + tag, min(a, b, o), 0, 0);
                E("max_" + tag, max(a, b, o), 0, 0);
                E3("addWeighted_" + tag, addWeighted(a, 0.37, b, -1.2, 3.3, o), it, ft, ft);
                E3("addWeighted2_" + tag, addWeighted(a, 0.5, b, 0.5, 0, o), it, ft, ft);
                E3("scaleAdd_" + tag, scaleAdd(a, -0.7, b, o), it, ft, ft);
                if (cn == 1) {
                    for (int op = CMP_EQ; op <= CMP_NE; op++)
                        E("cmp" + std::to_string(op) + "_" + tag, compare(a, b, o, op), 0, 0);
                    E("cmpS_" + tag, compare(a, s[0], o, CMP_GE), 0, 0);
                }
                E("inRange_" + tag, inRange(a, Scalar(lo / 3, lo / 4, lo / 5, lo / 6), Scalar(hi / 3, hi / 2, hi / 4, hi / 5), o), 0, 0);
                E("and_" + tag, bitwise_and(a, b, o), 0, 0);
                E("or_" + tag, bitwise_or(a, b, o), 0, 0);
                E("xor_" + tag, bitwise_xor(a, b, o), 0, 0);
                E("not_" + tag, bitwise_not(a, o), 0, 0);
                E("andM_" + tag, (o = Mat::zeros(sz, t), bitwise_and(a, b, o, mask)), 0, 0);
                E("addInPlace_" + tag, (o = a.clone(), add(o, b, o)), 0, 0);
                for (int dd : depths) {
                    E(std::string("cvt_") + dn(dd) + "_" + tag, a.convertTo(o, dd), 0, 0);
                    E3(std::string("cvtSc_") + dn(dd) + "_" + tag, a.convertTo(o, dd, 0.37, -5.5), dd >= CV_32F ? 0 : 1, fltTol(dd, 1e-6, 1e-14), fltTol(dd, 1e-6, 1e-14));
                }
                E("cvt_16f_" + tag, a.convertTo(o, CV_16F), 0, 0);
                E("cvtAbs_" + tag, convertScaleAbs(a, o, 0.11, 2), it, 0);
                const double rs = d >= CV_32F ? 1e-6 : 1e-12;
                V("sum_" + tag, 0, rs, { Scalar q = sum(a); for (int i = 0; i < 4; i++) v.push_back(q[i]); });
                V("meanM_" + tag, 0, rs, { Scalar q = mean(a, mask); for (int i = 0; i < 4; i++) v.push_back(q[i]); });
                V("meanStdDev_" + tag, 0, d >= CV_32F ? 1e-6 : 1e-9, { Scalar m1, s1; meanStdDev(a, m1, s1); for (int i = 0; i < 4; i++) { v.push_back(m1[i]); v.push_back(s1[i]); } });
                V("meanStdDevM_" + tag, 0, d >= CV_32F ? 1e-6 : 1e-9, { Scalar m1, s1; meanStdDev(a, m1, s1, mask); for (int i = 0; i < 4; i++) { v.push_back(m1[i]); v.push_back(s1[i]); } });
                for (int k : {NORM_INF, NORM_L1, NORM_L2, NORM_L2SQR}) {
                    const std::string nk = std::to_string(k) + "_" + tag;
                    V("norm" + nk, 0, rs, v.push_back(norm(a, k)));
                    V("normDiff" + nk, 0, rs, v.push_back(norm(a, b, k)));
                    V("normM" + nk, 0, rs, v.push_back(norm(a, k, mask)));
                    V("normDiffM" + nk, 0, rs, v.push_back(norm(a, b, k, mask)));
                    V("normRel" + nk, 0, rs, v.push_back(norm(a, b, k | NORM_RELATIVE)));
                }
                if (d == CV_8U && cn == 1) {
                    V("hamming_" + tag, 0, 0, { v.push_back(norm(a, b, NORM_HAMMING)); v.push_back(norm(a, NORM_HAMMING2)); });
                }
                if (cn == 1) {
                    V("countNZ_" + tag, 0, 0, { v.push_back(countNonZero(a)); v.push_back(hasNonZero(a) ? 1 : 0); });
                    V("minMaxLoc_" + tag, 0, 0, { double mn1, mx1; Point p1, p2; minMaxLoc(a, &mn1, &mx1, &p1, &p2);
                        v.push_back(mn1); v.push_back(mx1); v.push_back(p1.x); v.push_back(p1.y); v.push_back(p2.x); v.push_back(p2.y); });
                    V("minMaxLocM_" + tag, 0, 0, { double mn1, mx1; Point p1, p2; minMaxLoc(a, &mn1, &mx1, &p1, &p2, mask);
                        v.push_back(mn1); v.push_back(mx1); v.push_back(p1.x); v.push_back(p1.y); v.push_back(p2.x); v.push_back(p2.y); });
                }
                V("dot_" + tag, 0, rs, v.push_back(a.dot(b)));
                for (int dim = 0; dim < 2; dim++) {
                    const std::string rd = std::to_string(dim) + "_" + tag;
                    const int rt = d < CV_32F ? CV_64F : d;
                    E3("reduceSum" + rd, reduce(a, o, dim, REDUCE_SUM, rt), 0, fltTol(rt, 1e-5, 1e-12), fltTol(rt, 1e-5, 1e-12));
                    E3("reduceSum32_" + rd, reduce(a, o, dim, REDUCE_SUM, d < CV_32F ? CV_32S : CV_32F), 0, 1e-5, 1e-5);
                    E("reduceAvg" + rd, reduce(a, o, dim, REDUCE_AVG, CV_64F), 0, 1e-9);
                    E("reduceMax" + rd, reduce(a, o, dim, REDUCE_MAX), 0, 0);
                    E("reduceMin" + rd, reduce(a, o, dim, REDUCE_MIN), 0, 0);
                    E("reduceSum2" + rd, reduce(a, o, dim, REDUCE_SUM2, CV_64F), 0, 1e-9);
                }
                {
                    std::vector<Mat> ch;
                    try {
                        split(a, ch);
                        for (size_t i = 0; i < ch.size(); i++) emitMat(cx, "split" + std::to_string(i) + "_" + tag, ch[i], 0, 0);
                    } catch (const cv::Exception&) { emitExc(cx, "split_" + tag); }
                    std::reverse(ch.begin(), ch.end());
                    E("merge_" + tag, merge(ch, o), 0, 0);
                    if (cn > 1) E("extract_" + tag, extractChannel(a, o, cn - 1), 0, 0);
                    for (int fc = -1; fc <= 1; fc++) E("flip" + std::to_string(fc) + "_" + tag, flip(a, o, fc), 0, 0);
                    E("transpose_" + tag, transpose(a, o), 0, 0);
                }
                if (d == CV_8U || d == CV_8S) {
                    for (int ld : {CV_8U, CV_8S, CV_16U, CV_16S, CV_32S, CV_32F, CV_64F}) {
                        double llo, lhi; rangeOf(ld, llo, lhi);
                        Mat lut1 = randMat(r, Size(256, 1), CV_MAKETYPE(ld, 1), llo, lhi, false);
                        Mat lutn = randMat(r, Size(256, 1), CV_MAKETYPE(ld, cn), llo, lhi, false);
                        E(std::string("lut1_") + dn(ld) + "_" + tag, LUT(a, lut1, o), 0, 0);
                        E(std::string("lutN_") + dn(ld) + "_" + tag, LUT(a, lutn, o), 0, 0);
                    }
                }
                {
                    Mat m(cn, cn + 1, CV_32F); fillRandom(m, r, -2, 2);
                    E3("transform_" + tag, transform(a, o, m), it, d >= CV_32F ? 1e-5 : 0, d >= CV_32F ? 1e-6 : 0);
                    Mat m2(cn, cn, CV_64F); fillRandom(m2, r, -2, 2);
                    E3("transformSq_" + tag, transform(a, o, m2), it, d >= CV_32F ? 1e-5 : 0, d >= CV_32F ? 1e-6 : 0);
                }
            }
        }
        for (int d : {CV_32F, CV_64F}) {
            Size sz = pickSize(r);
            const bool view = r.below(2) == 0;
            const std::string tag = std::string(dn(d)) + "_" + std::to_string(sz.width) + "x" + std::to_string(sz.height) + (view ? "v" : "") + "_r" + std::to_string(round);
            Mat x = randMat(r, sz, d, -1000, 1000, view), y = randMat(r, sz, d, -1000, 1000, view);
            Mat pos = randMat(r, sz, d, 1e-6, 1e6, view), ex = randMat(r, sz, d, d == CV_32F ? -87 : -700, d == CV_32F ? 87 : 700, view);
            Mat ang = randMat(r, sz, d, -7, 7, view), small = randMat(r, sz, d, 0, 50, view);
            const double rt = d == CV_32F ? 1e-6 : 1e-14;
            Mat o, o2;
            E("magnitude_" + tag, magnitude(x, y, o), 0, rt);
            E("phase_" + tag, phase(x, y, o), 2e-4, 0);
            E("phaseDeg_" + tag, phase(x, y, o, true), 1e-2, 0);
            E("c2pMag_" + tag, cartToPolar(x, y, o, o2), 0, 1e-6);
            E("c2pAng_" + tag, cartToPolar(x, y, o2, o), 2e-4, 0);
            E("p2cX_" + tag, polarToCart(pos, ang, o, o2), 1e-3, 1e-5);
            E("p2cY_" + tag, polarToCart(pos, ang, o2, o), 1e-3, 1e-5);
            E("exp_" + tag, exp(ex, o), 0, rt);
            E("log_" + tag, log(pos, o), rt, rt);
            E("sqrt_" + tag, sqrt(pos, o), 0, rt);
            E("pow25_" + tag, pow(small, 2.5, o), 0, d == CV_32F ? 4e-6 : 1e-13);
            E("pow3_" + tag, pow(x, 3, o), 0, rt);
            E("pow05_" + tag, pow(pos, 0.5, o), 0, d == CV_32F ? 4e-6 : 1e-13);
            E("powm15_" + tag, pow(pos, -1.5, o), 0, d == CV_32F ? 4e-6 : 1e-13);
        }
        for (int d : {CV_8U, CV_16S, CV_32S}) {
            Size sz = pickSize(r);
            double lo, hi; rangeOf(d, lo, hi);
            Mat a = randMat(r, sz, d, lo / 64, hi / 64, false), o;
            E(std::string("powInt_") + dn(d) + "_r" + std::to_string(round), pow(a, 2, o), 0, 0);
        }
        for (int d : {CV_32F, CV_64F}) {
            const int m = 1 + r.below(70), n = 1 + r.below(70), k = 1 + r.below(70);
            const double rt = d == CV_32F ? 1e-4 : 1e-10;
            const std::string tag = std::string(dn(d)) + "_" + std::to_string(m) + "x" + std::to_string(n) + "x" + std::to_string(k) + "_r" + std::to_string(round);
            Mat A = randMat(r, Size(k, m), d, -1, 1, false), B = randMat(r, Size(n, k), d, -1, 1, false), Cm = randMat(r, Size(n, m), d, -1, 1, false);
            Mat At = A.t(), Bt = B.t(), Ct = Cm.t();
            Mat o;
            E("gemm_" + tag, gemm(A, B, 1.0, noArray(), 0, o), 1e-5, rt);
            E("gemmC_" + tag, gemm(A, B, -0.5, Cm, 1.5, o), 1e-5, rt);
            E("gemmAt_" + tag, gemm(At, B, 2.0, Cm, -1.0, o, GEMM_1_T), 1e-5, rt);
            E("gemmBtCt_" + tag, gemm(A, Bt, 1.0, Ct, 1.0, o, GEMM_2_T | GEMM_3_T), 1e-5, rt);
            E("mulTrA_" + tag, mulTransposed(A, o, true), 1e-5, rt);
            E("mulTrB_" + tag, mulTransposed(A, o, false), 1e-5, rt);
            Mat pts = randMat(r, Size(1 + r.below(500), 1), CV_MAKETYPE(d, 2), -100, 100, false);
            Matx33d H(1.01, 0.02, 3.0, -0.01, 0.98, -2.0, 1e-5, 2e-5, 1.0);
            E("persp_" + tag, perspectiveTransform(pts, o, H), 1e-5, d == CV_32F ? 1e-5 : 1e-12);
        }
    }
}

static int doCheck(uint64_t seed, const char* path) {
    FILE* f = fopen(path, "wb");
    if (!f) return 3;
    CheckCtx cx(seed, f);
    runChecks(cx, 3);
    fclose(f);
    fprintf(stderr, "check: %d records\n", cx.n);
    return 0;
}

// ------------------------------------------------------------------ comparison
struct Rec {
    std::string id; uint32_t depth; double ta, tr, tn; std::vector<double> v;
};
static bool readRec(FILE* f, Rec& r) {
    uint32_t magic, idlen; uint64_t n;
    if (fread(&magic, 4, 1, f) != 1) return false;
    if (magic != 0x52425643u || fread(&idlen, 4, 1, f) != 1 || idlen > 4096) throw 1;
    r.id.assign(idlen, ' ');
    if (fread(&r.id[0], 1, idlen, f) != idlen || fread(&r.depth, 4, 1, f) != 1 || fread(&n, 8, 1, f) != 1 ||
        fread(&r.ta, 8, 1, f) != 1 || fread(&r.tr, 8, 1, f) != 1 || fread(&r.tn, 8, 1, f) != 1 || n > (1ull << 31)) throw 1;
    r.v.resize(n);
    if (n && fread(r.v.data(), 8, n, f) != n) throw 1;
    return true;
}
// Prints one line per record: "<id> <ok 0|1> <n> <max abs diff> <max rel diff>", then "TOTAL <records> <failed>".
// Tolerances come from the first file (the trusted reference dump). An element passes when its difference is within
// the absolute tolerance, OR within tolRel times its own magnitude, OR within tolNorm times the largest magnitude in
// the record (a normwise bound for outputs that pass through zero).
static int doCmp(const char* pa, const char* pb) {
    FILE* fa = fopen(pa, "rb"); FILE* fb = fopen(pb, "rb");
    if (!fa) { printf("ERROR cannot open %s\n", pa); return 3; }
    int total = 0, failed = 0;
    try {
        Rec a, b;
        while (readRec(fa, a)) {
            total++;
            bool ok = fb && readRec(fb, b) && b.id == a.id && b.v.size() == a.v.size();
            double mabs = 0, mrel = 0, M = 0;
            if (ok) {
                for (double x : a.v) if (std::isfinite(x)) M = std::max(M, std::fabs(x));
                for (size_t i = 0; i < a.v.size(); i++) {
                    const double x = a.v[i], y = b.v[i];
                    if (std::isnan(x) || std::isnan(y)) { if (!(std::isnan(x) && std::isnan(y))) ok = false; continue; }
                    if (x == y) continue;
                    if (std::isinf(x) || std::isinf(y)) { ok = false; continue; }
                    const double ad = std::fabs(x - y), rd = ad / std::max(std::fabs(x), std::fabs(y));
                    mabs = std::max(mabs, ad); mrel = std::max(mrel, rd);
                    if (ad > a.ta && ad > a.tr * std::max(std::fabs(x), std::fabs(y)) && ad > a.tn * M) ok = false;
                }
            }
            if (!ok) failed++;
            printf("%s %d %zu %.6g %.6g\n", a.id.c_str(), ok ? 1 : 0, a.v.size(), mabs, mrel);
        }
    } catch (int) {
        printf("ERROR malformed dump\n");
        failed++;
    }
    printf("TOTAL %d %d\n", total, failed);
    if (fa) fclose(fa);
    if (fb) fclose(fb);
    return 0;
}

int main(int argc, char** argv) {
    cv::setNumThreads(1);
    if (argc >= 2 && !strcmp(argv[1], "list")) {
        std::vector<Case> cs = makeCases();
        for (size_t i = 0; i < cs.size(); i++)
            printf("%zu %s %s %d %d %g %g\n", i, cs[i].id, cs[i].family, cs[i].rows, cs[i].cols, cs[i].tolAbs, cs[i].tolRel);
        return 0;
    }
    if (argc >= 2 && !strcmp(argv[1], "serve")) return serve();
    if (argc >= 4 && !strcmp(argv[1], "check")) return doCheck(strtoull(argv[2], nullptr, 10), argv[3]);
    if (argc >= 4 && !strcmp(argv[1], "cmp")) return doCmp(argv[2], argv[3]);
    fprintf(stderr, "usage: cvbench list | serve | check <seed> <out> | cmp <a> <b>\n");
    return 2;
}
