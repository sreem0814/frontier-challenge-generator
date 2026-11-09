// server.cc: the HTTP server the wire cases talk to.  usage: server <port> <work dir>
//
// Raw request bytes go in over TCP; the raw response bytes come back and are compared byte for byte (after
// the multipart/byteranges boundary, which is random, is replaced by a fixed string).
// Routes (all bodies deterministic):
//   /echo...            any method: a dump of the parsed request (method, target, path, version, params,
//                       headers, trailers, body, multipart form)
//   /data/<n>           GET: n bytes of a fixed pattern (set_content), ETag "\"d<n>\""
//   /provider/<n>       GET: n bytes via set_content_provider with a length (7-byte writes)
//   /chunked/<n>        GET: n bytes via set_chunked_content_provider (5-byte writes, then a trailer)
//   /nolength/<n>       GET: n bytes via set_content_provider without a length
//   /reader             POST/PUT: HandlerWithContentReader; multipart parts or plain body pieces
//   /accept             GET: req.accept_content_types
//   /status/<n>         any method: that status, body "s<n>"
//   /redirect           GET: 302 to /data/3
//   /end                GET: "end" (the client side appends this request, with Connection: close, to every case)
//   /text/<n>           GET: n bytes of compressible text/plain (compression follows Accept-Encoding)
//   /static/...         mount point over <work dir>/www (files written here, fixed mtime)
#include <httplib.h>

#include <sys/stat.h>
#include <sys/time.h>
#include <utime.h>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>

using namespace httplib;

static std::string esc(const std::string &s) {
  static const char *hx = "0123456789abcdef";
  std::string o;
  for (unsigned char c : s) {
    if (c >= 0x20 && c < 0x7f && c != '\\') {
      o += static_cast<char>(c);
    } else {
      o += "\\x";
      o += hx[c >> 4];
      o += hx[c & 15];
    }
  }
  return o;
}

template <typename M> static std::string dump_map(const M &m) {
  std::string o = "{";
  for (auto &kv : m) o += "[" + esc(kv.first) + "=" + esc(kv.second) + "]";
  return o + "}";
}

static std::string pattern(size_t n) {
  std::string s;
  s.reserve(n);
  for (size_t i = 0; i < n; i++) s += static_cast<char>('A' + (i * 31 + i / 26) % 26);
  return s;
}

static size_t arg_n(const Request &req) {
  auto n = std::strtoull(req.matches[1].str().c_str(), nullptr, 10);
  return n > 1000000 ? 1000000 : static_cast<size_t>(n);
}

static void write_file(const std::string &path, const std::string &data) {
  std::ofstream f(path, std::ios::binary);
  f << data;
  f.close();
  struct utimbuf t;
  t.actime = 1700000000;
  t.modtime = 1700000000;
  utime(path.c_str(), &t);
}

int main(int argc, char **argv) {
  if (argc < 3) return 2;
  int port = atoi(argv[1]);
  std::string work = argv[2];
  std::string www = work + "/www";
  mkdir(www.c_str(), 0755);
  mkdir((www + "/dir").c_str(), 0755);
  write_file(www + "/a.txt", pattern(100));
  write_file(www + "/b.html", "<html><body>" + pattern(40) + "</body></html>\n");
  write_file(www + "/c.bin", pattern(3000));
  write_file(www + "/empty.txt", "");
  write_file(www + "/data.json", "{\"k\": \"" + pattern(20) + "\"}");
  write_file(www + "/dir/index.html", "<p>index</p>\n");
  write_file(www + "/sp ace.txt", "space\n");

  Server svr;
  svr.set_payload_max_length(65536);
  svr.set_read_timeout(2, 0);
  svr.set_write_timeout(2, 0);
  svr.set_keep_alive_max_count(16);
  svr.set_keep_alive_timeout(2);
  svr.set_mount_point("/static", www);

  auto echo = [](const Request &req, Response &res) {
    std::string o;
    o += "method=" + esc(req.method) + "\n";
    o += "target=" + esc(req.target) + "\n";
    o += "path=" + esc(req.path) + "\n";
    o += "version=" + esc(req.version) + "\n";
    o += "params=" + dump_map(req.params) + "\n";
    o += "headers=" + dump_map(req.headers) + "\n";
    o += "trailers=" + dump_map(req.trailers) + "\n";
    o += "body=" + esc(req.body) + "\n";
    o += "multipart=" + std::to_string(req.is_multipart_form_data()) + "\n";
    for (auto &f : req.form.fields)
      o += "field " + esc(f.first) + "=" + esc(f.second.content) + " h=" + dump_map(f.second.headers) + "\n";
    for (auto &f : req.form.files)
      o += "file " + esc(f.first) + " name=" + esc(f.second.filename) + " ct=" + esc(f.second.content_type) +
           " c=" + esc(f.second.content) + " h=" + dump_map(f.second.headers) + "\n";
    res.set_content(o, "text/plain");
  };
  for (auto m : {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}) {
    std::string mm = m;
    if (mm == "GET") svr.Get("/echo.*", echo);
    if (mm == "POST") svr.Post("/echo.*", echo);
    if (mm == "PUT") svr.Put("/echo.*", echo);
    if (mm == "PATCH") svr.Patch("/echo.*", echo);
    if (mm == "DELETE") svr.Delete("/echo.*", echo);
    if (mm == "OPTIONS") svr.Options("/echo.*", echo);
  }

  svr.Get(R"(/data/(\d+))", [](const Request &req, Response &res) {
    auto n = arg_n(req);
    res.set_header("ETag", "\"d" + std::to_string(n) + "\"");
    res.set_content(pattern(n), "application/octet-stream");
  });
  svr.Get(R"(/provider/(\d+))", [](const Request &req, Response &res) {
    auto n = arg_n(req);
    res.set_content_provider(n, "text/x-provider", [n](size_t offset, size_t length, DataSink &sink) {
      auto data = pattern(n);
      auto k = std::min<size_t>(length, 7);
      sink.write(data.data() + offset, k);
      return true;
    });
  });
  svr.Get(R"(/chunked/(\d+))", [](const Request &req, Response &res) {
    auto n = arg_n(req);
    res.set_chunked_content_provider("text/x-chunked", [n](size_t offset, DataSink &sink) {
      auto data = pattern(n);
      if (offset < n) {
        sink.write(data.data() + offset, std::min<size_t>(n - offset, 5));
      } else {
        Headers tr = {{"X-Sum", std::to_string(n)}};
        sink.done_with_trailer(tr);
      }
      return true;
    });
  });
  svr.Get(R"(/nolength/(\d+))", [](const Request &req, Response &res) {
    auto n = arg_n(req);
    res.set_content_provider("text/x-nolength", [n](size_t offset, DataSink &sink) {
      auto data = pattern(n);
      if (offset < n) {
        sink.write(data.data() + offset, std::min<size_t>(n - offset, 6));
      } else {
        sink.done();
      }
      return true;
    });
  });
  svr.Get(R"(/text/(\d+))", [](const Request &req, Response &res) {
    auto n = arg_n(req);
    std::string s;
    while (s.size() < n) s += "the quick brown fox jumps over the lazy dog ";
    s.resize(n);
    res.set_content(s, "text/plain");
  });
  auto reader = [](const Request &req, Response &res, const ContentReader &content_reader) {
    std::string o = "multipart=" + std::to_string(req.is_multipart_form_data()) + "\n";
    bool ok;
    if (req.is_multipart_form_data()) {
      ok = content_reader(
          [&](const FormData &f) {
            o += "part name=" + esc(f.name) + " file=" + esc(f.filename) + " ct=" + esc(f.content_type) +
                 " h=" + dump_map(f.headers) + "\n";
            return true;
          },
          [&](const char *d, size_t n) {
            o += "data " + esc(std::string(d, n)) + "\n";
            return true;
          });
    } else {
      std::string body;
      ok = content_reader([&](const char *d, size_t n) {
        body.append(d, n);
        return true;
      });
      o += "body=" + esc(body) + "\n";
    }
    o += "ok=" + std::to_string(ok) + "\n";
    o += "trailers=" + dump_map(req.trailers) + "\n";
    res.set_content(o, "text/plain");
  };
  svr.Post("/reader", reader);
  svr.Put("/reader", reader);
  svr.Get("/accept", [](const Request &req, Response &res) {
    std::string o;
    for (auto &t : req.accept_content_types) o += esc(t) + ";";
    res.set_content(o, "text/plain");
  });
  auto status = [](const Request &req, Response &res) {
    auto n = static_cast<int>(arg_n(req));
    res.status = n;
    res.set_content("s" + std::to_string(n), "text/plain");
  };
  svr.Get(R"(/status/(\d+))", status);
  svr.Post(R"(/status/(\d+))", status);
  svr.Get("/end", [](const Request &, Response &res) { res.set_content("end", "text/plain"); });
  svr.Get("/redirect", [](const Request &, Response &res) { res.set_redirect("/data/3"); });

  if (!svr.bind_to_port("127.0.0.1", port)) return 3;
  printf("ready\n");
  fflush(stdout);
  svr.listen_after_bind();
  return 0;
}
