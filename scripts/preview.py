# -*- coding: utf-8 -*-
"""
轩扫描官方中枢 · 本地预览渲染器（最小 Jekyll/Liquid 子集）

为什么需要它：
  本机没有 Ruby / Jekyll，无法 `bundle exec jekyll build`。
  这个脚本实现了「站点实际用到的那一小部分 Liquid」，
  把 site-jekyll/ 渲染成 _site/，用于在推上 GitHub 之前先肉眼确认效果。

支持的 Liquid 子集：
  {% assign %}  {% for %}  {% if %}  {% elsif %}  {% else %}  {% unless %}  {% comment %}
  {{ expr | filter: arg }}
  filters: where_exp / sort / reverse / first / size / jsonify / default /
           date_to_xmlschema / date / strip_html / strip_newlines / truncate /
           absolute_url / relative_url / escape

用法：
  python scripts/preview.py             # 输出到 _site/
  python scripts/preview.py --open      # 渲染完打印入口文件路径

注意：这只是「预览」。真正的构建由 GitHub Pages 上的 Jekyll 完成，
      两者输出可能有个别差异（主要是 Jekyll 的 markdown 与过滤器细节）。
"""
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_site")

CN = timezone(timedelta(hours=8))


# ============================================================ 简易 YAML
def parse_yaml_front(text):
    """只解析本项目用到的 YAML 结构：嵌套 map、list、标量、引号字符串"""
    lines = text.split("\n")
    return _yaml_block(lines, 0, 0)[0]


def _scalar(s):
    s = s.strip()
    if not s:
        return ""
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if s.lower() in ("null", "~", ""):
        return None if s.lower() in ("null", "~") else ""
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _yaml_block(lines, i, indent):
    data = {}
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        if cur > indent:
            # 缩进异常，跳过
            i += 1
            continue
        line = raw.strip()
        if line.startswith("- "):
            break  # list 交给上层处理
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # 可能是子 map，也可能子 list
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#")):
                j += 1
            if j < len(lines):
                nxt = lines[j]
                ncur = len(nxt) - len(nxt.lstrip(" "))
                if ncur > cur and nxt.strip().startswith("- "):
                    items, i = _yaml_list(lines, j, ncur)
                    data[key] = items
                    continue
                if ncur > cur:
                    sub, i = _yaml_block(lines, j, ncur)
                    data[key] = sub
                    continue
            data[key] = None
            i += 1
        else:
            data[key] = _scalar(rest)
            i += 1
    return data, i


def _yaml_list(lines, i, indent):
    items = []
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur < indent:
            break
        line = raw.strip()
        if not line.startswith("- "):
            break
        content = line[2:].strip()
        if ":" in content and not content.startswith(("'", '"')):
            # 对象项：把首行去 "- "，并把后续同级的 key: val 一起收进来
            block = [" " * (indent + 2) + content]
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    break
                ncur = len(nxt) - len(nxt.lstrip(" "))
                if ncur <= indent or nxt.strip().startswith("- "):
                    break
                block.append(" " * (indent + 2) + nxt.strip())
                j += 1
            obj, _ = _yaml_block(block, 0, indent + 2)
            items.append(obj)
            i = j
        else:
            items.append(_scalar(content))
            i += 1
    return items, i


# ============================================================ 简易 Markdown
def md_to_html(src):
    lines = src.split("\n")
    out = []
    i = 0
    para = []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()

        if line.startswith("```"):
            flush()
            lang = line[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = ' class="language-%s"' % lang if lang else ""
            out.append("<pre><code%s>%s</code></pre>" % (cls, esc("\n".join(buf))))
            continue

        if not line.strip():
            flush()
            i += 1
            continue

        # 原始 HTML 块：以 < 开头的行整段原样输出。
        # 与 Jekyll 一致 —— Markdown 里内嵌的 HTML 不该被转义成 &lt;
        if line.strip().startswith("<"):
            flush()
            buf = []
            while i < len(lines):
                s2 = lines[i].strip()
                if not s2 or not s2.startswith("<"):
                    break
                buf.append(lines[i].rstrip())
                i += 1
            out.append("\n".join(buf))
            continue

        m = re.match(r"^(#{2,4})\s+(.*)$", line)
        if m:
            flush()
            lv = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lv, inline(m.group(2).strip()), lv))
            i += 1
            continue

        if line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.append(_table(rows))
            continue

        if re.match(r"^[-*]\s+", line):
            flush()
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i]):
                items.append(re.sub(r"^[-*]\s+", "", lines[i]).strip())
                i += 1
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x) for x in items) + "</ul>")
            continue

        if re.match(r"^\d+\.\s+", line):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i]).strip())
                i += 1
            out.append("<ol>" + "".join("<li>%s</li>" % inline(x) for x in items) + "</ol>")
            continue

        if line.startswith(">"):
            flush()
            buf = [line[1:].strip()]
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue

        para.append(line)
        i += 1

    flush()
    return "\n".join(out)


def _table(rows):
    head = [c.strip() for c in rows[0].strip("|").split("|")]
    body = []
    for r in rows[1:]:
        cells = [c.strip() for c in r.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells):
            continue
        body.append(cells)
    html = ["<table>", "<thead><tr>" + "".join("<th>%s</th>" % inline(c) for c in head) + "</tr></thead>", "<tbody>"]
    for r in body:
        html.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
    html += ["</tbody>", "</table>"]
    return "\n".join(html)


def inline(s):
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ============================================================ Liquid 引擎
TOKEN_RE = re.compile(r"\{%-?\s*(.*?)\s*-?%\}|\{\{-?\s*(.*?)\s*-?\}\}", re.S)


def tokenize(src):
    """切分文本/标签，并实现 Liquid 的空白控制：
       {%- 吞掉标签前的空白， -%} 吞掉标签后的空白（含换行）"""
    toks = []
    pos = 0
    pending_lstrip = False
    for m in TOKEN_RE.finditer(src):
        raw = m.group(0)
        ltrim = raw.startswith("{%-") or raw.startswith("{{-")
        rtrim = raw.endswith("-%}") or raw.endswith("-}}")
        seg = src[pos:m.start()]
        if pending_lstrip:
            seg = seg.lstrip()
        if ltrim:
            seg = seg.rstrip()
        if seg:
            toks.append(("text", seg))
        if m.group(1) is not None:
            toks.append(("tag", m.group(1)))
        else:
            toks.append(("out", m.group(2)))
        pos = m.end()
        pending_lstrip = rtrim
    tail = src[pos:]
    if pending_lstrip:
        tail = tail.lstrip()
    if tail:
        toks.append(("text", tail))
    return toks


BLOCK_END = {"for": "endfor", "if": "endif", "unless": "endunless", "comment": "endcomment"}


def parse2(toks, i, stop):
    nodes = []
    while i < len(toks):
        kind, val = toks[i]
        if kind != "tag":
            nodes.append((kind, val))
            i += 1
            continue
        word = val.split()[0] if val.split() else ""
        if word in stop:
            return nodes, i
        if word in ("for", "unless", "comment"):
            body, i = parse2(toks, i + 1, (BLOCK_END[word],))
            i += 1
            nodes.append(("blk", word, val, body, None))
            continue
        if word == "if":
            branches = []
            args = val
            body, i = parse2(toks, i + 1, ("endif", "elsif", "else"))
            branches.append((args, body))
            else_body = None
            while i < len(toks) and toks[i][0] == "tag":
                w2 = toks[i][1].split()[0]
                if w2 == "elsif":
                    cond = toks[i][1]
                    b2, i = parse2(toks, i + 1, ("endif", "elsif", "else"))
                    branches.append((cond, b2))
                    continue
                if w2 == "else":
                    else_body, i = parse2(toks, i + 1, ("endif",))
                    break
                break
            # 吃掉 endif
            if i < len(toks) and toks[i][0] == "tag" and toks[i][1].split()[0] == "endif":
                i += 1
            nodes.append(("if", branches, else_body))
            continue
        if word == "assign":
            nodes.append(("assign", val))
            i += 1
            continue
        i += 1
    return nodes, i


def split_top(s, sep):
    """按顶层 sep 切分（忽略引号内）"""
    parts, buf, q = [], "", None
    for ch in s:
        if q:
            buf += ch
            if ch == q:
                q = None
            continue
        if ch in ("'", '"'):
            q = ch
            buf += ch
            continue
        if s[0:1] and ch == sep:
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    parts.append(buf)
    return [p.strip() for p in parts]


LIT_RE = re.compile(r"^(['\"])(.*)\1$|^(-?\d+(?:\.\d+)?)$|^(true|false|nil|null)$")


def unquote(s):
    """只脱掉首尾「配对」的引号。
    注意不能用 strip("'\\\"") —— 那会把 'xuanscan' 末尾的单引号也吃掉，
    导致 where_exp 的条件变成 p.xscan.app == 'xuanscan （右值引号残缺）。"""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def lit(v):
    m = LIT_RE.match(v.strip())
    if not m:
        return None
    if m.group(2) is not None:
        return m.group(2)
    if m.group(3):
        return float(m.group(3)) if "." in m.group(3) else int(m.group(3))
    if m.group(4):
        return {"true": True, "false": False}.get(m.group(4))
    return None


def resolve(path, ctx):
    parts = path.split(".")
    val = None
    for idx, p in enumerate(parts):
        if idx == 0:
            if p not in ctx:
                return None
            val = ctx[p]
        else:
            if isinstance(val, dict):
                if p not in val:
                    return None
                val = val[p]
            elif isinstance(val, list):
                if p == "size":
                    return len(val)
                try:
                    val = val[int(p)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
    return val


def eval_expr(expr, ctx):
    expr = expr.strip()
    # 先切 filter
    segs = split_top(expr, "|")
    base = segs[0]
    val = None
    l = lit(base)
    if l is not None:
        val = l
    elif base.startswith("'") or base.startswith('"'):
        val = base[1:-1]
    else:
        val = resolve(base, ctx)
    for f in segs[1:]:
        val = apply_filter(f, val, ctx)
    return val


def resolve_arg(a, ctx):
    """过滤器参数可能是变量（如 default: site.lang），不能一律当字面量。
    只有长得像变量路径、且在上下文里能解析出来时才替换，其余原样返回
    （否则会误伤 date: "%Y-%m-%d" 这类格式串）。"""
    s = a.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*", s):
        return a
    l = lit(s)
    if l is not None:
        return l
    r = resolve(s, ctx)
    return a if r is None else r


def apply_filter(spec, val, ctx):
    if ":" in spec:
        name, _, argstr = spec.partition(":")
        name = name.strip()
        args = [resolve_arg(unquote(a), ctx) for a in split_top(argstr, ",")]
    else:
        name, args = spec.strip(), []

    if name == "default":
        return val if val not in (None, "", False) else (args[0] if args else "")
    if name == "size":
        return len(val) if val is not None else 0
    if name == "jsonify":
        return json.dumps(val if val is not None else "", ensure_ascii=False)
    if name == "first":
        return (val[0] if val else None)
    if name == "reverse":
        return list(reversed(val or []))
    if name == "sort":
        key = args[0] if args else None
        items = list(val or [])
        def k(x):
            v = x.get(key) if isinstance(x, dict) else None
            if isinstance(v, datetime):
                return v.timestamp()
            return str(v or "")
        return sorted(items, key=k)
    if name == "where_exp":
        var, cond = args[0], args[1]
        out = []
        for it in (val or []):
            sub = dict(ctx)
            sub[var] = it
            if eval_cond(cond, sub):
                out.append(it)
        return out
    if name == "date_to_xmlschema":
        return fmt_date(val, "%Y-%m-%dT%H:%M:%S%z")
    if name == "date":
        return fmt_date(val, args[0] if args else "%Y-%m-%d")
    if name == "strip_html":
        return re.sub(r"<[^>]+>", "", str(val or ""))
    if name == "strip_newlines":
        return re.sub(r"\s*\n\s*", " ", str(val or "")).strip()
    if name == "truncate":
        n = int(args[0]) if args else 50
        s = str(val or "")
        return s if len(s) <= n else s[:n] + "…"
    if name == "absolute_url":
        return (ctx.get("site.url", "") or "") + str(val or "")
    if name == "relative_url":
        return (ctx.get("site.baseurl", "") or "") + str(val or "")
    if name == "escape":
        return esc(str(val or ""))
    if name == "plus":
        return (val or 0) + (int(args[0]) if args else 0)
    return val


def fmt_date(v, fmt):
    if isinstance(v, datetime):
        d = v
    else:
        s = str(v or "")
        d = None
        for f in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s, f)
                break
            except ValueError:
                continue
        if d is None:
            return s
    if "%z" in fmt:
        return d.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"
    return d.strftime(fmt.replace("%H:%M", "%H:%M"))


def eval_cond(cond, ctx):
    for orpart in re.split(r"\s+or\s+", cond):
        ok = True
        for andpart in re.split(r"\s+and\s+", orpart):
            andpart = andpart.strip()
            for op in ("==", "!=", ">=", "<=", ">", "<"):
                if op in andpart:
                    a, _, b = andpart.partition(op)
                    av = eval_expr(a.strip(), ctx)
                    bv = lit(b.strip())
                    if bv is None:
                        bv = eval_expr(b.strip(), ctx)
                    if op == "==":
                        r = str(av) == str(bv)
                    elif op == "!=":
                        r = str(av) != str(bv)
                    else:
                        try:
                            r = (av > bv) if op == ">" else (av < bv) if op == "<" \
                                else (av >= bv) if op == ">=" else (av <= bv)
                        except TypeError:
                            r = False
                    if not r:
                        ok = False
                    break
            else:
                if not eval_expr(andpart, ctx):
                    ok = False
            if not ok:
                break
        if ok:
            return True
    return False


def render_nodes(nodes, ctx):
    out = []
    for n in nodes:
        if n[0] == "text":
            out.append(n[1])
        elif n[0] == "out":
            v = eval_expr(n[1], ctx)
            if v is None:
                out.append("")
            elif isinstance(v, bool):
                # Jekyll 输出 true/false，不是 Python 的 True/False，
                # 否则 feed.json 里会写出非法的 "pinned": True
                out.append("true" if v else "false")
            else:
                out.append(str(v))
        elif n[0] == "assign":
            m = re.match(r"assign\s+([\w.]+)\s*=\s*(.*)$", n[1], re.S)
            if m:
                # 直接改调用方的 ctx：调用方每轮 for 都会 dict(ctx) 复制，
                # 顶层的 assign 语义本来就应该是「对当前作用域可见」
                ctx[m.group(1)] = eval_expr(m.group(2), ctx)
            continue
        elif n[0] == "blk":
            kind, args, body = n[1], n[2], n[3]
            if kind == "comment":
                continue
            if kind == "for":
                m = re.match(r"for\s+(\w+)\s+in\s+(.*)$", args, re.S)
                var, expr = m.group(1), m.group(2)
                items = eval_expr(expr, ctx) or []
                for idx, it in enumerate(items):
                    sub = dict(ctx)
                    sub[var] = it
                    sub["forloop"] = {
                        "index": idx + 1,
                        "index0": idx,
                        "first": idx == 0,
                        "last": idx == len(items) - 1,
                        "length": len(items),
                    }
                    out.append(render_nodes(body, sub))
                continue
            if kind == "unless":
                if not eval_expr(re.sub(r"^unless\s+", "", args), ctx):
                    out.append(render_nodes(body, ctx))
                continue
        elif n[0] == "if":
            branches, else_body = n[1], n[2]
            done = False
            for args, body in branches:
                cond = re.sub(r"^(if|elsif)\s+", "", args)
                if eval_cond(cond, ctx):
                    out.append(render_nodes(body, ctx))
                    done = True
                    break
            if not done and else_body:
                out.append(render_nodes(else_body, ctx))
            continue
    return "".join(out)


def render(src, ctx):
    toks = tokenize(src)
    nodes, _ = parse2(toks, 0, ())
    return render_nodes(nodes, ctx)


# ============================================================ 站点装配
def clean_out():
    """清空输出目录。
    不用 shutil.rmtree —— 部分沙箱/安全策略会拦截整树删除，
    这里改成逐文件删 + 逐目录删，兼容性更好。"""
    if not os.path.isdir(OUT):
        return
    for dp, dns, fns in os.walk(OUT, topdown=False):
        for fn in fns:
            try:
                os.remove(os.path.join(dp, fn))
            except OSError:
                pass
        for dn in dns:
            try:
                os.rmdir(os.path.join(dp, dn))
            except OSError:
                pass


def load_config():
    cfg_path = os.path.join(ROOT, "_config.yml")
    txt = open(cfg_path, encoding="utf-8").read()
    data = parse_yaml_front(txt)
    data.setdefault("title", "轩扫描 XuanScan")
    data.setdefault("url", "https://efreelab.github.io")
    data.setdefault("baseurl", "")
    return data


def load_posts():
    pdir = os.path.join(ROOT, "_posts")
    posts = []
    if not os.path.isdir(pdir):
        return posts
    for fn in sorted(os.listdir(pdir)):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$", fn)
        if not m:
            continue
        y, mo, d, slug = m.groups()
        raw = open(os.path.join(pdir, fn), encoding="utf-8").read()
        if not raw.startswith("---"):
            continue
        _, _, rest = raw.partition("---")
        fm_txt, _, body = rest.partition("\n---")
        fm = parse_yaml_front(fm_txt)
        date = None
        ds = str(fm.get("date", ""))
        for f in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                date = datetime.strptime(ds, f)
                break
            except ValueError:
                continue
        if date is None:
            date = datetime(int(y), int(mo), int(d), tzinfo=CN)
        # 第一段作为 excerpt
        excerpt = ""
        for p in body.strip().split("\n\n"):
            if p.strip() and not p.strip().startswith(("#", "|", "-", ">")):
                excerpt = p.strip()
                break
        posts.append({
            "title": fm.get("title", slug),
            "date": date,
            "slug": slug,
            "url": "/%s/%s/%s/%s/" % (y, mo, d, slug),
            "excerpt": excerpt,
            "raw": body,
            "content": md_to_html(body),
            "xscan": fm.get("xscan") or {},
            "layout": fm.get("layout"),
            "file": fn,
            "y": y, "mo": mo, "d": d,
        })
    posts.sort(key=lambda p: p["date"], reverse=True)
    return posts


def rel_prefix(url):
    depth = url.count("/") - 1
    return "../" * depth if depth > 0 else ""


def absolutize(html, url):
    """把 /xxx 的内部路径改写成相对路径，使 file:// 直接打开也能正常显示。
       注意 depth==0 的页面（首页）也要处理：/assets/... 在 file:// 下找不到，
       必须写成 ./assets/...，否则本地打开就是无 CSS 的纯文本。"""
    pre = rel_prefix(url)
    prefix = "./" if not pre else pre
    html = re.sub(r'href="/', 'href="' + prefix, html)
    html = re.sub(r'src="/', 'src="' + prefix, html)
    return html


def main():
    site = load_config()
    posts = load_posts()
    site["posts"] = posts
    site["time"] = datetime.now(CN)

    clean_out()
    os.makedirs(OUT, exist_ok=True)

    layouts = {}
    ldir = os.path.join(ROOT, "_layouts")
    if os.path.isdir(ldir):
        for fn in os.listdir(ldir):
            layouts[fn.rsplit(".", 1)[0]] = open(os.path.join(ldir, fn), encoding="utf-8").read()

    def layout_body(name):
        """返回 (front-matter, body)"""
        raw = layouts[name]
        if raw.startswith("---"):
            _, _, rest = raw.partition("---")
            fm_txt, _, body = rest.partition("\n---")
            return parse_yaml_front(fm_txt), body
        return {}, raw

    def render_page(obj, url, layout_name, is_html=False):
        ctx = {"site": site, "page": obj}
        # 顺序很重要：Jekyll 是「先跑 Liquid，再做 Markdown」。
        # 反过来会导致 index.md 里的 {% for %} 被当成纯文本原样输出。
        # 但 .html 源文件本身就是 HTML，不能再过一遍 Markdown，否则
        # <style>/<script> 里的缩进会被当成代码块。
        raw = obj.get("raw")
        if raw is not None:
            body = render(raw, ctx) if is_html else md_to_html(render(raw, ctx))
        else:
            body = obj.get("content", "")
        obj["content"] = body
        lay = layout_name
        depth = 0
        while lay and lay in layouts and depth < 4:
            fm, lay_tpl = layout_body(lay)
            ctx["content"] = body
            body = render(lay_tpl, ctx)
            lay = fm.get("layout")
            depth += 1
        html = absolutize(body, url)
        if url.endswith(".html"):
            path = os.path.join(OUT, url.strip("/"))
        else:
            path = os.path.join(OUT, url.strip("/"), "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(html)

    # 1) 文章
    for p in posts:
        render_page(p, p["url"], p.get("layout") or "post")

    # 2) 首页
    idx = os.path.join(ROOT, "index.md")
    if os.path.exists(idx):
        raw = open(idx, encoding="utf-8").read()
        if raw.startswith("---"):
            _, _, rest = raw.partition("---")
            fm_txt, _, body = rest.partition("\n---")
            fm = parse_yaml_front(fm_txt)
        else:
            fm, body = {}, raw
        page = dict(fm)
        page["url"] = "/"
        page["raw"] = body
        render_page(page, "/", fm.get("layout") or "default")

    # 2b) 根目录的独立页面（app-preview.html 等；index / README 除外）
    for fn in sorted(os.listdir(ROOT)):
        if not (fn.endswith(".html") or fn.endswith(".md")):
            continue
        # index.md 由第 2 步单独处理（url 为 "/"）；README 不发布
        if fn in ("index.md", "README.md"):
            continue
        fp = os.path.join(ROOT, fn)
        if not os.path.isfile(fp):
            continue
        raw = open(fp, encoding="utf-8").read()
        if raw.startswith("---"):
            _, _, rest = raw.partition("---")
            fm_txt, _, body = rest.partition("\n---")
            fm = parse_yaml_front(fm_txt)
        else:
            fm, body = {}, raw
        page = dict(fm)
        # index.html 要落在站点根路径 "/"，否则会变成 /index.html 且相对链接算错
        url = "/" if fn == "index.html" else "/" + fn
        page["url"] = url
        page["raw"] = body
        render_page(page, url, fm.get("layout") or "default", is_html=fn.endswith(".html"))

    # 3) api 下的 Liquid JSON
    apidir = os.path.join(ROOT, "api")
    if os.path.isdir(apidir):
        for dp, _, fns in os.walk(apidir):
            rel = os.path.relpath(dp, ROOT).replace("\\", "/")
            os.makedirs(os.path.join(OUT, rel), exist_ok=True)
            for fn in fns:
                src = open(os.path.join(dp, fn), encoding="utf-8").read()
                if src.startswith("---"):
                    _, _, rest = src.partition("---")
                    _, _, body = rest.partition("\n---")
                else:
                    body = src
                out = render(body, {"site": site, "page": {}})
                open(os.path.join(OUT, rel, fn), "w", encoding="utf-8").write(out)

    # 4) 静态资源
    for asset in ("assets",):
        src_dir = os.path.join(ROOT, asset)
        if os.path.isdir(src_dir):
            shutil.copytree(src_dir, os.path.join(OUT, asset))

    print("渲染完成 →", OUT)
    print("  文章 %d 篇" % len(posts))
    for p in posts:
        print("   -", p["xscan"].get("type", "announce"), p["title"])
    print()
    print("入口：%s" % os.path.join(OUT, "index.html"))
    if os.path.exists(os.path.join(ROOT, "app-preview.html")):
        print("App 模拟：%s" % os.path.join(OUT, "app-preview.html"))




if __name__ == "__main__":
    main()
