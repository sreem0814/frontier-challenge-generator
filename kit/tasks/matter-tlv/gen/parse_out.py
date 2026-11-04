"""Parse case_runner output into {id: (bucket, status, transcript bytes)}; also usable as a library."""
import sys


def parse(data):
    res, pos, n = {}, 0, len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split(b" ")
        pos = nl + 1
        if len(head) == 4 and head[0] == b"C" and head[3].isdigit():
            ln = int(head[3])
            res.setdefault(head[1].decode(), (head[2].decode(), "C", data[pos:pos + ln]))
            pos += ln
        elif len(head) >= 3 and head[0] == b"X":
            res.setdefault(head[1].decode(), (head[2].decode(), "X", b" ".join(head[3:])))
        else:
            break  # unframed output: stop; later cases count as missing
    return res


if __name__ == "__main__":
    a = parse(open(sys.argv[1], "rb").read())
    b = parse(open(sys.argv[2], "rb").read())
    same = sum(1 for k in a if k in b and a[k][1] == "C" and a[k] == b[k])
    print(f"{len(a)} vs {len(b)} cases; identical {same}")
    for k in sorted(a):
        if k in b and a[k][1] == "C" and a[k] == b[k]:
            print("SAME", k, a[k][0])
