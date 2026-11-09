// probe.cc: library-level and client-side cases for httplib.h.
//
// Reads one case per line from stdin: <id> TAB <op> TAB <hex arg> TAB <hex arg> ...
// Writes one line per case to stdout:  <id> TAB <escaped result>   (flushed after every case)
// Escaping: bytes 0x20-0x7e except '\' are written as is, every other byte as \xHH.
//
// Client cases ("cli") run a scripted raw-socket peer in a thread of this process (plain POSIX sockets, no
// httplib code): it accepts each connection, records the request bytes, answers with the scripted bytes and
// closes. The result holds what the client returned and the requests the peer received.
#include <httplib.h>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

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

static std::string unhex(const std::string &h) {
  std::string o;
  for (size_t i = 0; i + 1 < h.size(); i += 2) {
    o += static_cast<char>(std::stoi(h.substr(i, 2), nullptr, 16));
  }
  return o;
}

static std::vector<std::string> split(const std::string &s, char d) {
  std::vector<std::string> v;
  std::string cur;
  for (char c : s) {
    if (c == d) {
      v.push_back(cur);
      cur.clear();
    } else {
      cur += c;
    }
  }
  v.push_back(cur);
  return v;
}

static size_t num(const std::string &s) { return s.empty() ? 0 : static_cast<size_t>(std::stoull(s)); }

static std::vector<size_t> sizes(const std::string &s) {
  std::vector<size_t> v;
  if (s.empty()) return v;
  for (auto &x : split(s, ',')) v.push_back(num(x));
  return v;
}

template <typename M> static std::string dump_map(const M &m) {
  std::string o = "{";
  for (auto &kv : m) o += "[" + esc(kv.first) + "=" + esc(kv.second) + "]";
  return o + "}";
}

static std::string dump_ranges(const Ranges &r) {
  std::string o = "[";
  for (auto &x : r) o += "(" + std::to_string(x.first) + "," + std::to_string(x.second) + ")";
  return o + "]";
}

// "k: v" lines separated by \n -> Headers (split at the first ':', one optional space)
static Headers to_headers(const std::string &s) {
  Headers h;
  if (s.empty()) return h;
  for (auto &l : split(s, '\n')) {
    auto p = l.find(':');
    if (p == std::string::npos) continue;
    auto v = l.substr(p + 1);
    if (!v.empty() && v[0] == ' ') v = v.substr(1);
    h.emplace(l.substr(0, p), v);
  }
  return h;
}

// k=v pairs separated by \n -> Params (no decoding)
static Params to_params(const std::string &s) {
  Params p;
  if (s.empty()) return p;
  for (auto &l : split(s, '\n')) {
    auto q = l.find('=');
    if (q == std::string::npos) p.emplace(l, "");
    else p.emplace(l.substr(0, q), l.substr(q + 1));
  }
  return p;
}

// items separated by \x1e, fields by \x1f: name, content, filename, content_type
static UploadFormDataItems to_items(const std::string &s) {
  UploadFormDataItems items;
  if (s.empty()) return items;
  for (auto &it : split(s, '\x1e')) {
    auto f = split(it, '\x1f');
    while (f.size() < 4) f.push_back("");
    items.push_back({f[0], f[1], f[2], f[3]});
  }
  return items;
}

static std::string buf_stream_rest(detail::BufferStream &bs) {
  std::string rest;
  char b[4096];
  for (;;) {
    auto n = bs.read(b, sizeof(b));
    if (n <= 0) break;
    rest.append(b, static_cast<size_t>(n));
  }
  return rest;
}

// ---------------------------------------------------------------------------------------------------------
// Scripted peer for client cases
struct Peer {
  int lfd = -1;
  int port = 0;
  std::vector<std::string> responses;  // one per accepted connection; extra connections are closed at once
  std::vector<std::string> requests;
  std::vector<std::string> slots;
  std::vector<std::thread> workers;
  std::atomic<bool> stop{false};
  std::thread th;

  bool start() {
    lfd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (lfd < 0) return false;
    int one = 1;
    setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in a{};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = 0;
    if (::bind(lfd, reinterpret_cast<sockaddr *>(&a), sizeof(a)) != 0) return false;
    socklen_t al = sizeof(a);
    getsockname(lfd, reinterpret_cast<sockaddr *>(&a), &al);
    port = ntohs(a.sin_port);
    if (::listen(lfd, 8) != 0) return false;
    th = std::thread([this] { run(); });
    return true;
  }

  static bool wait_in(int fd, int ms) {
    pollfd p{fd, POLLIN, 0};
    return ::poll(&p, 1, ms) > 0;
  }

  static std::string lower(std::string s) {
    for (auto &c : s) c = static_cast<char>(tolower(static_cast<unsigned char>(c)));
    return s;
  }

  // Read one request: the head, then a Content-Length body or a chunked body (up to the last-chunk and the
  // blank line after the trailers). Stops after 1.5 s without data.
  static std::string read_request(int fd) {
    std::string d;
    char b[65536];
    auto more = [&]() {
      if (!wait_in(fd, 1500)) return false;
      auto n = ::recv(fd, b, sizeof(b), 0);
      if (n <= 0) return false;
      d.append(b, static_cast<size_t>(n));
      return true;
    };
    while (d.find("\r\n\r\n") == std::string::npos)
      if (!more()) return d;
    auto he = d.find("\r\n\r\n") + 4;
    auto head = lower(d.substr(0, he));
    auto cl = head.find("\r\ncontent-length:");
    if (cl != std::string::npos) {
      size_t n = std::strtoull(head.c_str() + cl + 17, nullptr, 10);
      while (d.size() < he + n)
        if (!more()) return d;
    } else if (head.find("\r\ntransfer-encoding: chunked") != std::string::npos) {
      size_t pos = he;
      for (;;) {
        auto le = d.find("\r\n", pos);
        while (le == std::string::npos) {
          if (!more()) return d;
          le = d.find("\r\n", pos);
        }
        size_t sz = std::strtoull(d.c_str() + pos, nullptr, 16);
        if (sz == 0) {
          while (d.find("\r\n\r\n", le) == std::string::npos && d.compare(le, 4, "\r\n\r\n") != 0) {
            if (d.size() >= le + 2 && d.compare(le, 4, "\r\n\r\n") == 0) break;
            if (!more()) return d;
          }
          return d;
        }
        while (d.size() < le + 2 + sz + 2)
          if (!more()) return d;
        pos = le + 2 + sz + 2;
      }
    }
    return d;
  }

  void serve(int fd, size_t idx) {
    auto req = read_request(fd);
    slots[idx] = req;
    auto r = responses[idx];
    std::string ps = std::to_string(port), out;
    for (size_t i = 0; i < r.size();) {  // "{PORT}" -> the real port
      if (r.compare(i, 6, "{PORT}") == 0) {
        out += ps;
        i += 6;
      } else {
        out += r[i++];
      }
    }
    size_t off = 0;
    while (off < out.size()) {
      auto n = ::send(fd, out.data() + off, out.size() - off, MSG_NOSIGNAL);
      if (n <= 0) break;
      off += static_cast<size_t>(n);
    }
    ::shutdown(fd, SHUT_WR);
    while (wait_in(fd, 200)) {  // drain what the client still sends, then close
      char b[4096];
      if (::recv(fd, b, sizeof(b), 0) <= 0) break;
    }
    ::close(fd);
  }

  // Each connection is served on its own thread, so a slow close of one never delays the next; the n-th accepted
  // connection gets the n-th scripted response.
  void run() {
    size_t idx = 0;
    slots.assign(responses.size(), std::string());
    while (!stop.load()) {
      if (!wait_in(lfd, 50)) continue;
      int fd = ::accept(lfd, nullptr, nullptr);
      if (fd < 0) continue;
      if (idx >= responses.size()) {
        ::close(fd);
        continue;
      }
      workers.emplace_back([this, fd, idx] { serve(fd, idx); });
      idx++;
    }
    for (auto &w : workers) w.join();
    for (auto &r : slots)
      if (!r.empty()) requests.push_back(r);
  }

  void finish() {
    stop = true;
    if (th.joinable()) th.join();
    if (lfd >= 0) ::close(lfd);
  }
};

static std::string unport(const std::string &s, int port) {
  std::string ps = std::to_string(port), o;
  for (size_t i = 0; i < s.size();) {
    if (s.compare(i, ps.size(), ps) == 0 && i > 0 && s[i - 1] == ':') {
      o += "{PORT}";
      i += ps.size();
    } else {
      o += s[i++];
    }
  }
  return o;
}

// args: 0 kind, 1 path, 2 headers, 3 body or items or params, 4 responses (separated by \0\0CONN\0\0),
//       5 flags (comma list), 6 content type, 7 boundary
static std::string run_client(const std::vector<std::string> &a) {
  Peer peer;
  std::string scr = a[4];
  const std::string sep = std::string("\0\0CONN\0\0", 8);
  size_t p = 0;
  for (;;) {
    auto q = scr.find(sep, p);
    peer.responses.push_back(scr.substr(p, q == std::string::npos ? std::string::npos : q - p));
    if (q == std::string::npos) break;
    p = q + sep.size();
  }
  if (!peer.start()) return "PEERFAIL";
  std::string out;
  {
    Client cli("127.0.0.1", peer.port);
    cli.set_connection_timeout(2);
    cli.set_read_timeout(2);
    cli.set_write_timeout(2);
    auto flags = split(a[5], ',');
    auto has = [&](const char *f) {
      for (auto &x : flags)
        if (x == f) return true;
      return false;
    };
    cli.set_follow_location(has("follow"));
    cli.set_compress(has("compress"));
    cli.set_decompress(!has("nodecompress"));
    cli.set_keep_alive(has("keepalive"));
    if (has("nopathencode")) cli.set_path_encode(false);
    if (has("maxlen")) cli.set_payload_max_length(4096);
    auto hdrs = to_headers(a[2]);
    const auto &kind = a[0];
    const auto &path = a[1];
    std::string recv_body;
    Result res{nullptr, Error::Unknown};
    bool use_res = true;
    if (kind == "get") {
      res = cli.Get(path, hdrs);
    } else if (kind == "get_params") {
      res = cli.Get(path, to_params(a[3]), hdrs);
    } else if (kind == "get_recv") {
      res = cli.Get(path, hdrs, [&](const char *d, size_t n) {
        recv_body.append(d, n);
        return true;
      });
    } else if (kind == "get_ranges") {
      Ranges rs;
      for (auto &x : split(a[3], ';')) {
        auto ab = split(x, ',');
        if (ab.size() == 2) rs.emplace_back(std::stoll(ab[0]), std::stoll(ab[1]));
      }
      auto rh = make_range_header(rs);
      hdrs.insert(rh);
      res = cli.Get(path, hdrs);
    } else if (kind == "head") {
      res = cli.Head(path, hdrs);
    } else if (kind == "delete") {
      res = cli.Delete(path, hdrs, a[3], a[6]);
    } else if (kind == "options") {
      res = cli.Options(path, hdrs);
    } else if (kind == "post") {
      res = cli.Post(path, hdrs, a[3], a[6]);
    } else if (kind == "put") {
      res = cli.Put(path, hdrs, a[3], a[6]);
    } else if (kind == "patch") {
      res = cli.Patch(path, hdrs, a[3], a[6]);
    } else if (kind == "post_params") {
      res = cli.Post(path, hdrs, to_params(a[3]));
    } else if (kind == "post_form") {
      res = cli.Post(path, hdrs, to_items(a[3]), a[7]);
    } else if (kind == "put_form") {
      res = cli.Put(path, hdrs, to_items(a[3]), a[7]);
    } else if (kind == "post_chunked") {
      auto body = a[3];
      auto parts = sizes(a[7]);
      res = cli.Post(path, hdrs, [body, parts](size_t offset, DataSink &sink) {
        size_t off = 0;
        for (auto n : parts) {
          if (off >= body.size()) break;
          n = std::min(n, body.size() - off);
          sink.write(body.data() + off, n);
          off += n;
        }
        if (off < body.size()) sink.write(body.data() + off, body.size() - off);
        (void)offset;
        sink.done();
        return true;
      }, a[6]);
    } else if (kind == "post_provider") {
      auto body = a[3];
      res = cli.Post(path, hdrs, body.size(), [body](size_t offset, size_t length, DataSink &sink) {
        size_t n = std::min<size_t>(length, 7);
        sink.write(body.data() + offset, n);
        return true;
      }, a[6]);
    } else if (kind == "stream") {
      use_res = false;
      auto h = cli.open_stream("GET", path, Params(), hdrs, "", "");
      out += "valid=" + std::to_string(h.is_valid()) + " err=" + to_string(h.error);
      if (h.response) {
        out += " status=" + std::to_string(h.response->status) + " ver=" + esc(h.response->version) +
               " reason=" + esc(h.response->reason) + " headers=" + dump_map(h.response->headers);
        char b[37];
        std::string body;
        for (int i = 0; i < 100000; i++) {
          auto n = h.read(b, sizeof(b));
          if (n <= 0) {
            out += " last=" + std::to_string(n > 0 ? 1 : static_cast<int>(n));
            break;
          }
          body.append(b, static_cast<size_t>(n));
        }
        h.parse_trailers_if_needed();
        out += " body=" + esc(body) + " readerr=" + to_string(h.get_read_error()) +
               " trailers=" + dump_map(h.response->trailers);
      }
    } else {
      use_res = false;
      out = "BADKIND";
    }
    if (use_res) {
      out += "err=" + to_string(res.error());
      if (res) {
        out += " status=" + std::to_string(res->status) + " ver=" + esc(res->version) + " reason=" +
               esc(res->reason) + " headers=" + dump_map(res->headers) + " body=" + esc(res->body) +
               " trailers=" + dump_map(res->trailers) + " location=" + esc(res->location);
      }
      if (kind == "get_recv") out += " recv=" + esc(recv_body);
    }
  }
  peer.finish();
  out += " requests=" + std::to_string(peer.requests.size());
  for (auto &r : peer.requests) out += " <" + esc(r) + ">";
  return unport(out, peer.port);
}

// ---------------------------------------------------------------------------------------------------------
static std::string run_case(const std::string &op, const std::vector<std::string> &a) {
  std::ostringstream o;
  if (op == "hdr") {  // parse_header on one field line
    std::vector<std::pair<std::string, std::string>> kv;
    auto ok = detail::parse_header(a[0].data(), a[0].data() + a[0].size(),
                                   [&](const std::string &k, const std::string &v) { kv.emplace_back(k, v); });
    o << "ok=" << ok;
    for (auto &x : kv) o << " [" << esc(x.first) << "=" << esc(x.second) << "]";
  } else if (op == "fields") {
    o << detail::fields::is_token(a[0]) << detail::fields::is_field_name(a[0])
      << detail::fields::is_field_value(a[0]) << detail::fields::is_field_content(a[0])
      << detail::fields::is_request_target(a[0]) << detail::fields::is_host(a[0])
      << detail::fields::is_field_valid(a[0], a[1]);
  } else if (op == "status") {
    std::string ver, reason;
    int st = -7;
    auto ok = detail::parse_status_line(a[0].c_str(), ver, st, reason);
    o << "ok=" << ok;
    if (ok) o << " ver=" << esc(ver) << " st=" << st << " reason=" << esc(reason);
  } else if (op == "readhdr") {
    detail::BufferStream bs;
    bs.write(a[0].data(), a[0].size());
    Headers h;
    auto ok = detail::read_headers(bs, h);
    o << "ok=" << ok;
    if (ok) o << " h=" << dump_map(h) << " rest=" << esc(buf_stream_rest(bs));
  } else if (op == "lines") {
    detail::BufferStream bs;
    bs.write(a[0].data(), a[0].size());
    char fixed[16];
    detail::stream_line_reader r(bs, fixed, sizeof(fixed));
    for (int i = 0; i < 64; i++) {
      if (!r.getline()) {
        o << "end";
        break;
      }
      o << "<" << esc(std::string(r.ptr(), r.size())) << "|" << r.end_with_crlf() << ">";
    }
  } else if (op == "resphead") {
    detail::BufferStream bs;
    bs.write(a[0].data(), a[0].size());
    int st = -7;
    Headers h;
    auto ok = detail::read_response_head(bs, st, h);
    o << "ok=" << ok;
    if (ok) o << " st=" << st << " h=" << dump_map(h) << " rest=" << esc(buf_stream_rest(bs));
  } else if (op == "te") {
    auto h = to_headers(a[0]);
    o << detail::is_chunked_transfer_encoding(h) << detail::has_conflicting_content_length(h);
  } else if (op == "chunk") {
    detail::BufferStream bs;
    bs.write(a[0].data(), a[0].size());
    detail::ChunkedDecoder dec(bs);
    auto rs = sizes(a[1]);
    std::string data;
    size_t i = 0;
    for (int guard = 0; guard < 100000; guard++) {
      size_t want = rs.empty() ? 64 : rs[i++ % rs.size()];
      std::vector<char> b(want ? want : 1);
      size_t co = 99999, ct = 99999;
      auto n = dec.read_payload(b.data(), want, co, ct);
      if (n < 0) {
        o << "err ";
        break;
      }
      if (n == 0) {
        o << "eof ";
        break;
      }
      data.append(b.data(), static_cast<size_t>(n));
      o << n << ":" << co << "/" << ct << " ";
    }
    o << "data=" << esc(data) << " fin=" << dec.finished;
    Headers tr;
    auto ok = dec.parse_trailers_into(tr, to_headers(a[2]));
    o << " tok=" << ok << " tr=" << dump_map(tr) << " rest=" << esc(buf_stream_rest(bs));
  } else if (op == "content") {  // read_content into a Response with the given headers
    detail::BufferStream bs;
    bs.write(a[1].data(), a[1].size());
    Response x;
    x.headers = to_headers(a[0]);
    int status = -7;
    // Only call-granularity-independent facts are printed: the bytes, the last progress report, whether the
    // receiver offsets were contiguous, and the set of total_length values seen.
    std::string body, last_prog = "-";
    bool contig = true;
    std::set<size_t> totals;
    auto ok = detail::read_content(
        bs, x, num(a[2]), status, [&](size_t cur, size_t total) {
          last_prog = std::to_string(cur) + "/" + std::to_string(total);
          return true;
        },
        [&](const char *d, size_t n, size_t off, size_t total) {
          if (off != body.size()) contig = false;
          body.append(d, n);
          totals.insert(total);
          return true;
        },
        a[3] == "1");
    o << "ok=" << ok << " status=" << status << " body=" << esc(body) << " trailers=" << dump_map(x.trailers)
      << " rest=" << esc(buf_stream_rest(bs));
    if (a[4] == "1") {
      o << " prog=" << last_prog << " contig=" << contig << " totals=";
      for (auto t : totals) o << t << ",";
    }
  } else if (op == "bodyreader") {
    detail::BufferStream bs;
    bs.write(a[0].data(), a[0].size());
    detail::BodyReader br;
    br.stream = &bs;
    br.chunked = a[1] == "chunked";
    br.has_content_length = a[1] == "length";
    br.content_length = num(a[2]);
    br.payload_max_length = num(a[3]);
    if (br.chunked) br.chunked_decoder.reset(new detail::ChunkedDecoder(bs));
    std::string data;
    char b[13];
    for (int guard = 0; guard < 100000; guard++) {
      auto n = br.read(b, sizeof(b));
      if (n <= 0) {
        o << "last=" << n << " ";
        break;
      }
      data.append(b, static_cast<size_t>(n));
    }
    o << "data=" << esc(data) << " eof=" << br.eof << " read=" << br.bytes_read
      << " err=" << to_string(br.last_error);
  } else if (op == "url") {
    detail::UrlComponents uc;
    auto ok = detail::parse_url(a[0], uc);
    o << "ok=" << ok;
    if (ok)
      o << " s=" << esc(uc.scheme) << " h=" << esc(uc.host) << " p=" << esc(uc.port) << " path=" << esc(uc.path)
        << " q=" << esc(uc.query);
  } else if (op == "relloc") {
    o << esc(detail::resolve_relative_location(a[0], a[1]));
  } else if (op == "enc") {
    const auto &s = a[0];
    o << esc(encode_uri_component(s)) << " | " << esc(encode_uri(s)) << " | " << esc(decode_uri_component(s))
      << " | " << esc(decode_uri(s)) << " | " << esc(encode_path_component(s)) << " | "
      << esc(decode_path_component(s)) << " | " << esc(encode_query_component(s, true)) << " | "
      << esc(encode_query_component(s, false)) << " | " << esc(decode_query_component(s, true)) << " | "
      << esc(decode_query_component(s, false)) << " | " << esc(detail::encode_path(s)) << " | "
      << esc(detail::encode_request_target(s, true)) << " | " << esc(detail::encode_request_target(s, false))
      << " | " << esc(sanitize_filename(s));
  } else if (op == "query") {
    Params p;
    detail::parse_query_text(a[0], p);
    o << dump_map(p) << " str=" << esc(detail::params_to_query_str(p))
      << " norm=" << esc(detail::normalize_query_string(a[0]));
  } else if (op == "append") {
    o << esc(append_query_params(a[0], to_params(a[1]))) << " | " << esc(detail::params_to_query_str(to_params(a[1])));
  } else if (op == "boundary") {
    std::string b;
    auto ok = detail::parse_multipart_boundary(a[0], b);
    o << "ok=" << ok << " b=" << esc(b) << " valid=" << detail::is_multipart_boundary_chars_valid(a[0]);
  } else if (op == "dispo") {
    Params p;
    detail::parse_disposition_params(a[0], p);
    o << dump_map(p);
  } else if (op == "form") {  // FormDataParser fed in the given pieces
    detail::FormDataParser fp;
    fp.set_boundary(std::string(a[0]));
    auto rs = sizes(a[2]);
    const auto &body = a[1];
    std::vector<std::pair<char, std::string>> ev;  // adjacent data events merged: piece boundaries do not matter
    bool ok = true;
    size_t off = 0, i = 0;
    while (off < body.size() && ok) {
      size_t n = rs.empty() ? body.size() : std::max<size_t>(1, rs[i++ % rs.size()]);
      n = std::min(n, body.size() - off);
      ok = fp.parse(body.data() + off, n,
                    [&](const FormData &f) {
                      ev.emplace_back('H', "name=" + esc(f.name) + " file=" + esc(f.filename) +
                                               " ct=" + esc(f.content_type) + " h=" + dump_map(f.headers));
                      return true;
                    },
                    [&](const char *d, size_t len) {
                      if (!ev.empty() && ev.back().first == 'D') ev.back().second.append(d, len);
                      else ev.emplace_back('D', std::string(d, len));
                      return true;
                    });
      off += n;
    }
    std::string merged;
    for (auto &e : ev) merged += e.first == 'H' ? "{H " + e.second + "}" : "{D " + esc(e.second) + "}";
    o << "ok=" << ok << " valid=" << fp.is_valid() << " ev=" << merged;
  } else if (op == "mpser") {
    auto items = to_items(a[0]);
    o << esc(detail::serialize_multipart_formdata(items, a[1], a[2] == "1"))
      << " len=" << detail::get_multipart_content_length(items, a[1]);
    auto prov = detail::make_multipart_content_provider(items, a[1]);
    std::string got;
    DataSink sink;
    sink.write = [&](const char *d, size_t n) {
      got.append(d, n);
      return true;
    };
    sink.is_writable = []() { return true; };
    size_t total = detail::get_multipart_content_length(items, a[1]);
    size_t off = 0;
    for (int guard = 0; guard < 10000 && off < total; guard++) {
      size_t before = got.size();
      if (!prov(off, std::min<size_t>(total - off, 5), sink)) break;
      if (got.size() == before) break;
      off = got.size();
    }
    o << " prov=" << esc(got) << " esc=" << esc(detail::escape_multipart_field(a[3])) << "|"
      << esc(detail::escape_multipart_field(a[3], false));
  } else if (op == "range") {
    Ranges r;
    auto ok = detail::parse_range_header(a[0], r);
    o << "ok=" << ok << " r=" << dump_ranges(r);
    if (ok) {
      auto len = num(a[1]);
      auto c = r;
      detail::coalesce_ranges(c, len);
      o << " co=" << dump_ranges(c);
      Request req;
      req.ranges = r;
      Response res;
      res.status = 200;
      res.body = std::string(len, 'x');
      auto err = detail::range_error(req, res);
      o << " err=" << err << " st=" << res.status << " rr=" << dump_ranges(req.ranges);
      if (!err) {
        for (auto &x : req.ranges) {
          auto ol = detail::get_range_offset_and_length(x, len);
          o << " [" << ol.first << "+" << ol.second << " " << esc(detail::make_content_range_header_field(ol, len))
            << "]";
        }
      }
    }
  } else if (op == "rangehdr") {
    Ranges rs;
    for (auto &x : split(a[0], ';')) {
      auto ab = split(x, ',');
      if (ab.size() == 2) rs.emplace_back(std::stoll(ab[0]), std::stoll(ab[1]));
    }
    auto h = make_range_header(rs);
    o << esc(h.first) << ": " << esc(h.second);
  } else if (op == "mranges") {
    Request req;
    detail::parse_range_header(a[0], req.ranges);
    auto len = num(a[1]);
    Response res;
    std::string data;
    for (size_t i = 0; i < len; i++) data += static_cast<char>('a' + (i * 7) % 26);
    res.body = data;
    res.status = 200;
    if (req.ranges.empty() || detail::range_error(req, res)) {
      o << "skip";
      return o.str();
    }
    std::string out;
    detail::make_multipart_ranges_data(req, res, "BOUNDARY", a[2], len, out);
    o << esc(out) << " len=" << detail::get_multipart_ranges_data_length(req, "BOUNDARY", a[2], len);
  } else if (op == "accept") {
    std::vector<std::string> v;
    auto ok = detail::parse_accept_header(a[0], v);
    o << "ok=" << ok << " [";
    for (auto &x : v) o << esc(x) << ";";
    o << "]";
  } else if (op == "media") {
    std::map<std::string, std::string> p;
    auto m = detail::extract_media_type(a[0], &p);
    o << esc(m) << " " << dump_map(p) << " noq=" << esc(detail::remove_quoted_strings(a[0]))
      << " unq=" << esc(detail::unescape_quoted_pairs(a[0])) << " q=" << esc(detail::escape_quoted_pairs(a[0]));
  } else if (op == "quality") {
    std::string tok;
    double q = -1;
    auto ok = detail::parse_quality(a[0].data(), a[0].data() + a[0].size(), tok, q);
    char qb[32];
    snprintf(qb, sizeof(qb), "%.4f", q);
    o << "ok=" << ok << " tok=" << esc(tok) << " q=" << (ok ? qb : "-");
  } else if (op == "encoding") {
    Request req;
    req.headers = to_headers(a[0]);
    auto t = detail::encoding_type(req, a[1]);
    o << static_cast<int>(t);
  } else if (op == "wwwauth") {
    Response res;
    res.headers = to_headers(a[0]);
    std::map<std::string, std::string> auth;
    auto ok = detail::parse_www_authenticate(res, auth, a[1] == "1");
    o << "ok=" << ok << " " << dump_map(auth);
  } else if (op == "cli") {
    o << run_client(a);
  } else {
    o << "BADOP";
  }
  return o.str();
}

int main() {
  std::ios::sync_with_stdio(false);
  std::string line;
  while (std::getline(std::cin, line)) {
    auto f = split(line, '\t');
    if (f.size() < 2) continue;
    std::vector<std::string> args;
    for (size_t i = 2; i < f.size(); i++) args.push_back(unhex(f[i]));
    while (args.size() < 8) args.push_back("");
    std::string r;
#ifndef CPPHTTPLIB_NO_EXCEPTIONS
    try {
      r = run_case(f[1], args);
    } catch (...) {
      r = "EXC";
    }
#else
    r = run_case(f[1], args);
#endif
    std::cout << f[0] << '\t' << r << '\n' << std::flush;
  }
  return 0;
}
