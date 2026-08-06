"""Luna 的「手」：7 个工具 handler、传给模型的 TOOLS schema，以及分发器 guarded_execute。

loop 每步拿到模型的 tool_use 请求后就在这里执行，结果为字符串，作为用户消息返回模型。
"""
from __future__ import annotations

from typing import Optional

# sandbox 是路径封闭与隔离目录的唯一 owner，tools 只消费它的 resolve_in_workdir / PathEscape，不重复实现。
from agent import sandbox
import os
import re
import shlex
import subprocess
import sys

# 跨工具共享的噪声目录——真实仓库可能极大，list_dir/search 一律跳过，避免读满内存
NOISE_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", ".git",
    ".venv", "venv", "env", "node_modules", "dist", "build", ".eggs",
    ".idea", ".vscode", "htmlcov", ".next", "target",
}
# apply_patch 的两个标量护栏：patch 体积上限，以及 git apply 子进程的墙钟上限。
MAX_PATCH_CHARS = 60_000
GIT_APPLY_TIMEOUT_S = 30

_BINARY_EXTS = {
    ".pyc", ".so", ".o", ".a", ".dylib", ".dll", ".exe", ".bin", ".zip",
    ".gz", ".tar", ".whl", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico",
    ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".db", ".sqlite",
}


def _in_git_dir(workdir: str, abs_path: str) -> bool:
    """abs_path 是否落在仓库的 .git/ 内——不许工具改写真实仓库的 git 元数据。"""
    rel = os.path.relpath(abs_path, os.path.realpath(workdir))
    return rel == ".git" or rel.startswith(".git" + os.sep)


def is_test_path(path: str) -> bool:
    """粗粒度识别测试文件路径；apply_patch 和 run_repo 的反作弊共用这一份判断。

    按路径分量判断而非前缀，嵌套的 src/tests/、pkg/test/ 一样要拦住；宁可误伤也不放过。
    """
    rel = os.path.normpath(path).replace(os.sep, "/")
    parts = rel.split("/")
    base = parts[-1]
    return (
        any(part in ("tests", "test") for part in parts[:-1])
        or base in ("tests", "test", "conftest.py")
        or (base.startswith("test_") and base.endswith(".py"))
        or base.endswith("_test.py")
    )


# ---------------------------------------------------------------------------
# TOOLS —— 7 个 tool schema，直接传给 client.messages.create(tools=TOOLS, ...)。
# 每个是 {"name", "description", "input_schema"}，input_schema 是标准 JSON Schema，都带
# "additionalProperties": false，描述用英文。
# ---------------------------------------------------------------------------
TOOLS: list[dict] = [
    {
        "name": "list_dir",
        "description": (
            "List the entries of a directory inside the task workspace. "
            "Entries are returned in alphabetical order with directories suffixed by '/'. "
            "Noise such as __pycache__, .pytest_cache, *.pyc and .git is filtered out."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to list, relative to the workspace root. Defaults to '.'.",
                    "default": ".",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file inside the task workspace and return its content with "
            "1-based, right-aligned line numbers. Use start_line/end_line (1-based, inclusive) "
            "to read a slice of large files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File to read, relative to the workspace root.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to show (1-based, inclusive). Defaults to 1.",
                    "default": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to show (1-based, inclusive). Omit to read to the end of the file.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": (
            "Search for a literal (case-sensitive, non-regex) substring across text files inside "
            "the task workspace. Matches are returned as 'relative/path:line: text'. Restrict the "
            "scope with 'path' (a subdirectory, or a single file)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Literal substring to look for (case-sensitive).",
                },
                "path": {
                    "type": "string",
                    "description": "Subdirectory or file to search under, relative to the workspace root. Defaults to '.'.",
                    "default": ".",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace an exact, unique occurrence of old_string with new_string in an existing file. "
            "The edit is applied only when old_string appears exactly once. "
            "old_string matches the file's raw content; do NOT include the line-number / tab prefix "
            "that read_file shows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File to edit, relative to the workspace root.",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find; must appear exactly once in the file (raw content, no line-number prefix).",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text.",
                },
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a UTF-8 text file inside the task workspace, creating parent "
            "directories as needed. Use this to create new files; use edit_file to modify existing ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File to write, relative to the workspace root.",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write (overwrites any existing content).",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a standard unified diff inside the task workspace. Use this for multi-line "
            "or multi-file edits after reading the relevant context. The patch is checked before "
            "it is applied. It must not touch tests or .git metadata, and renames or copies are "
            "rejected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": (
                        "A standard unified diff, for example output shaped like "
                        "'--- a/file.py', '+++ b/file.py', '@@ ...', then -/+ lines."
                    ),
                },
            },
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_tests",
        "description": (
            "Run pytest inside the task workspace and report PASS/FAIL with a compact failure "
            "summary. Optionally pass 'path' to scope to a test file, a directory, or a node id "
            "(e.g. tests/test_parser.py::test_unary_minus); omit to run the full suite."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Test file, directory, or node id to run, relative to the workspace root. Omit to run everything.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# 7 个工具 handler
# ---------------------------------------------------------------------------
def list_dir(workdir: str, path: str = ".") -> str:
    """列出 path 目录下的条目，字母序排列，目录名带尾部 /，过滤掉 __pycache__、.pyc、.git 之类的噪声。

    首行是目录名，其余每行一个条目、两空格缩进；路径都用 workdir 相对形式。目录不存在、path 指向
    文件、过滤后为空各有对应的提示串。
    """
    abs_path = sandbox.resolve_in_workdir(workdir, path)
    if not os.path.exists(abs_path):
        return f"错误：目录不存在：{path}"
    if not os.path.isdir(abs_path):
        return f"错误：不是目录：{path}"
    
    names = [
        n for n in os.listdir(abs_path)
        if n not in NOISE_DIRS and not n.endswith(".pyc")
    ]
    names.sort()

    entries = []
    for name in names:
        full = os.path.join(abs_path, name)
        entries.append(name + "/" if os.path.isdir(full) else name)
    if not entries:
        return f"{path}/：（空目录）"

    lines = [f"{path}/："]                 # 首行：目录名
    lines += ["  " + e for e in entries]  # 每条两空格缩进
    return "\n".join(lines)

def read_file(
    workdir: str,
    path: str,
    start_line: int = 1,
    end_line: Optional[int] = None,
    max_read_lines: int = 400,
) -> str:
    """读文本文件并带右对齐行号返回；start_line/end_line（1-based、含端点）可读大文件的某一段。

    start_line 太小夹到 1，end_line 超尾夹到末行；起始行超过总行数、start_line 大于 end_line、
    空文件、疑似二进制（utf-8 解码失败）各有对应错误串。单次最多显示 max_read_lines 行（默认 400），
    超了只给前 N 行并提示用 start_line/end_line 分段读。头部给出总行数和显示范围。
    """
    abs_path = sandbox.resolve_in_workdir(workdir, path)
    if not os.path.exists(abs_path):
        return f"错误：文件不存在：{path}"
    if os.path.isdir(abs_path):
        return f"错误：该路径对应目录而非文件：{path}"
    
    try:
        with open(abs_path, encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return f"错误：无法以文本读取文件：{path}"
    
    lines = content.splitlines()
    total = len(lines)
    if total == 0:
        return f"空文件：{path}"
    if end_line is None:
        end_line = total          
    if start_line < 1:
        start_line = 1            
    if end_line > total:
        end_line = total          
    if start_line > total:
        return f"错误：起始行 {start_line} 超过文件总行数 {total}"
    if start_line > end_line:
        return f"错误：start_line {start_line} 大于 end_line {end_line}"
    truncated = False
    last = end_line
    if last - start_line + 1 > max_read_lines:
        last = start_line + max_read_lines - 1
        truncated = True
    header = f"{path}（共 {total} 行，显示 {start_line}-{last} 行）："
    body = [f"{n:>6}\t{lines[n-1]}" for n in range(start_line, last + 1)]
    out = header + "\n" + "\n".join(body)
    if truncated:
        out += f"\n…（已截断，共 {total} 行，用 start_line/end_line 分段读取）"
    return out

def search(
    workdir: str,
    query: str,
    path: str = ".",
    max_search_hits: int = 100,
) -> str:
    """在仓库里做字面子串检索：大小写敏感、不走正则（MVP 保持简单）。

    以 path 为根递归（path 指向文件就只搜那个文件），命中输出 "relpath:lineno: text"，跳过二进制、
    无法解码的文件以及噪声目录。最多 max_search_hits 条（默认 100），单行超 200 字符截断，超上限会
    提示缩小 query 或 path；query 为空、无命中各有对应提示串。命中行逐条列出，末尾附计数。
    """
    if len(query) == 0:
        return f"错误：搜索关键字不能为空"
    root = os.path.realpath(workdir)
    search_path = sandbox.resolve_in_workdir(workdir, path)

    files = []
    if os.path.isfile(search_path):
        files.append(search_path)                          # path 指向单个文件
    else:
        for dirpath, dirnames, filenames in os.walk(search_path):
            dirnames[:] = sorted(d for d in dirnames if d not in NOISE_DIRS)  # 剪枝 + 排序
            for name in sorted(filenames):
                if os.path.splitext(name)[1] in _BINARY_EXTS:
                    continue                               # 跳过二进制/编译产物
                files.append(os.path.join(dirpath, name))

    hits = []
    truncated = False
    for full in files:
        try:
            if os.path.getsize(full) > 1_000_000:          # 跳过 >1MB 的大文件（真实仓库防 OOM）
                continue
            with open(full, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        rel = os.path.relpath(full, root)                   
        for lineno, line in enumerate(lines, start=1):      
            if query in line:                               
                if len(line) > 200:
                    line = line[:200] + "…"
                hits.append(f"{rel}:{lineno}: {line}")
                if len(hits) >= max_search_hits:
                    truncated = True
                    break
        if truncated:
            break

    if not hits:
        return f"（无匹配）：{query}"
    out = "\n".join(hits) + f"\n共 {len(hits)} 处匹配。"
    if truncated:
        out += f"\n…（命中过多，仅显示前 {max_search_hits} 条，请缩小 query 或 path）"
    return out

def edit_file(workdir: str, path: str, old_string: str, new_string: str) -> str:
    """只在 old_string 唯一出现时才替换——这样编辑是确定性的，也逼模型先 read_file 看清上下文再改。

    old_string 没找到、出现多次、与 new_string 相同（空操作，白耗步数）都拒绝并原样保留文件；文件
    不存在会提示改用 write_file，目标是目录也有对应错误串。成功时回确认信息 + 替换处起始行号 +
    改后那几行上下文（带行号，最多约 5 行）。
    """
    if old_string == new_string:
        return "错误：old_string 与 new_string 相同，无需修改。"
    abs_path = sandbox.resolve_in_workdir(workdir, path)
    if _in_git_dir(workdir, abs_path):
        return f"错误：拒绝写入 .git/ 内的文件：{path}"
    if not os.path.exists(abs_path):
        return f"错误：文件不存在：{abs_path} (如需新建请用 write_file)"
    if not os.path.isfile(abs_path):
        return f"错误：该路径对应的不是文件：{abs_path}"
    
    try:
        with open(abs_path, encoding="utf-8") as f:
            content = f.read()

        n = content.count(old_string)          
        if n == 0:
            return f"错误：old_string 未在文件中找到，未做修改。"
        if n > 1:
            return f"错误：old_string 在文件中出现 {n} 次，不唯一，未做修改。"

        new_content = content.replace(old_string, new_string)
        with open(abs_path, "w", encoding="utf-8") as f:   # "w" = 覆盖整个文件
            f.write(new_content)

        offset = content.index(old_string)         
        start_line = content[:offset].count("\n") + 1   # old_string 所在行数
        new_lines = new_content.splitlines()
        end = min(start_line + 4, len(new_lines))          # start_line 起，最多 5 行
        context = "\n".join(
            f"{i:>6}\t{new_lines[i - 1]}" for i in range(start_line, end + 1)
        )
        return f"已替换 {path}（第 {start_line} 行）：\n{context}"
    
    except UnicodeDecodeError:
        return f"错误：文件 {abs_path} 打开失败，请检查是否为二进制格式"
    
def write_file(workdir: str, path: str, content: str) -> str:
    """创建或覆盖文本文件，父目录按需创建，utf-8 写入。

    写前先记一下文件是否已存在，用来区分回执里说「创建」还是「覆盖」。目标规范化后是已存在目录则报错。
    """
    abs_path = sandbox.resolve_in_workdir(workdir, path)
    if _in_git_dir(workdir, abs_path):
        return f"错误：拒绝写入 .git/ 内的文件：{path}"
    if os.path.isdir(abs_path):
        return f"错误：目标是一个目录：{abs_path}"
    existed = os.path.exists(abs_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    n_bytes = len(content.encode("utf-8"))
    n_lines = len(content.splitlines())
    return f"已{'覆盖' if existed else '创建'} {path}（{n_bytes} 字节，{n_lines} 行）。"


def _git_apply(workdir: str, patch: str, *args: str) -> subprocess.CompletedProcess:
    """跑一次 git apply；args 决定是只探查还是真落盘。"""
    return subprocess.run(
        ["git", "apply", "--whitespace=nowarn", *args],
        cwd=workdir,
        input=patch,
        capture_output=True,
        text=True,
        timeout=GIT_APPLY_TIMEOUT_S,
    )


def apply_patch(workdir: str, patch: str) -> str:
    """先让 git 自己枚举 patch 会碰哪些文件，逐个过护栏，再真正落盘。

    路径一律取自 git apply --numstat，不自己解析 ---/+++ 行：手写解析看不见
    rename/copy/binary 这类扩展头，模型只要把改名操作夹在一个正常 hunk 后面，
    就能把测试文件整个挪走而护栏毫无察觉。
    """
    if not patch or not patch.strip():
        return "错误：patch 不能为空。"
    if len(patch) > MAX_PATCH_CHARS:
        return f"错误：patch 过长（{len(patch)} 字符），请拆成更小的补丁。"

    # 一次 dry-run 拿三样东西：能不能应用（返回码）、会碰哪些文件（--numstat）、
    # 有没有 rename/copy（--summary）。
    probe = _git_apply(workdir, patch, "--check", "--numstat", "-z", "--summary")
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "").strip()
        return f"错误：patch 无法应用，未做修改。\n{detail[-2000:]}"

    # --numstat -z 的记录以 NUL 结尾，--summary 的行以换行结尾且排在最后，
    # 所以最后一个 NUL 之后剩下的就是 summary 块。
    records, _, summary = probe.stdout.rpartition("\0")

    # rename/copy 的两端在 --summary 里是 {a => b} 压缩写法，与其解析不如直接拒掉：
    # 修 bug 让测试通过用不着改名，放行则等于给测试文件保护开后门。
    for line in summary.splitlines():
        if line.strip().split(" ", 1)[0] in ("rename", "copy"):
            return (
                "错误：apply_patch 不接受重命名/复制文件的 patch（会绕过测试文件保护）。"
                "如需新建文件请用 write_file。"
            )

    paths = [rec.split("\t", 2)[2] for rec in records.split("\0") if rec]
    if not paths:
        return "错误：patch 没有产生任何文件改动。"

    for path in paths:
        abs_path = sandbox.resolve_in_workdir(workdir, path)
        if _in_git_dir(workdir, abs_path):
            return f"错误：拒绝修改 .git/ 内的文件：{path}"
        if is_test_path(path):
            return f"错误：拒绝通过 apply_patch 修改测试文件：{path}"

    applied = _git_apply(workdir, patch)
    if applied.returncode != 0:
        detail = (applied.stderr or applied.stdout or "").strip()
        return f"错误：patch 应用失败，未做修改。\n{detail[-2000:]}"

    listed = "\n".join(f"  - {path}" for path in paths[:20])
    extra = f"\n  …（另有 {len(paths) - 20} 个）" if len(paths) > 20 else ""
    return f"已应用 patch，涉及 {len(paths)} 个文件：\n{listed}{extra}"


def run_tests(
    workdir: str,
    path: Optional[str] = None,
    timeout: int = 60,
    max_test_output: int = 4000,
    test_cmd: Optional[str] = None,
    test_python: Optional[str] = None,
) -> str:
    """在 workspace 里跑测试并回报 PASS/FAIL。
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # 不写 __pycache__ 弄脏工作树

    # generic: 只按退出码粗判
    if test_cmd:
        try:
            gr = subprocess.run(
                shlex.split(test_cmd), cwd=workdir, capture_output=True,
                text=True, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired as e:
            partial = e.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", "replace")
            return f"错误：测试运行超时（>{timeout}s），已终止。\n部分输出：\n{partial[-1000:]}"
        tail = ((gr.stdout or "") + (gr.stderr or ""))[-max_test_output:]
        verdict = "PASS" if gr.returncode == 0 else "FAIL"
        return (f"[run_tests] 命令：{test_cmd}\n结果：{verdict}（returncode={gr.returncode}，"
                f"仅按退出码判定）\n输出（尾部）：\n{tail}")

    # 1. path 校验：只对 "::" 之前的文件部分做路径封闭（越界抛 PathEscape，交给护栏）。
    if path:
        file_part = path.split("::", 1)[0]
        sandbox.resolve_in_workdir(workdir, file_part)

    # 2. 组命令、在 workdir 里跑 pytest（解释器可注入=目标仓库自己的 venv；
    #    --continue-on-collection-errors：一个无关文件收集失败不整轮中断）。
    cmd = [
        test_python or sys.executable, "-m", "pytest",
        "-q", "--tb=short", "-rfE", "--color=no",
        "--continue-on-collection-errors",
        "-p", "no:cacheprovider",
    ]
    if path:
        cmd.append(path)
    try:
        result = subprocess.run(
            cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired as e:
        partial = e.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return (
            f"错误：测试运行超时（>{timeout}s），已终止——可能改坏后引入死循环或无限递归。\n"
            f"部分输出：\n{partial[-1000:]}"
        )

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    rc = result.returncode
    target = path if path else "全量"

    # 3. 从汇总行抽统计（仅展示、不作判定）。
    stats = "、".join(
        f"{num} {kind}"
        for num, kind in re.findall(
            r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)", stdout
        )
    ) or "无统计"

    # 4. 按 returncode 定性。
    if rc == 5:
        return f"[run_tests] 目标：{target}\n警告：未收集到任何测试（检查 path / 测试是否存在）"
    if rc in (2, 3, 4):
        return (
            f"[run_tests] 目标：{target}\n错误：pytest 自身异常（returncode={rc}）\n"
            f"{stderr[-1000:]}"
        )

    verdict = "PASS" if rc == 0 else "FAIL"
    head = f"[run_tests] 目标：{target}\n结果：{verdict}（returncode={rc}）\n统计：{stats}"
    if rc == 0:
        return head

    # 5. rc == 1：失败清单（-rfE 短行，永远保留）+ 失败详情（按预算截断）。
    fail_lines = [ln for ln in stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    fails = "\n".join(fail_lines) if fail_lines else "（无 FAILED/ERROR 明细行）"

    detail = ""
    if "= FAILURES =" in stdout:
        detail = stdout.split("= FAILURES =", 1)[1]
        detail = detail.split("= short test summary", 1)[0].strip("=\n ")
    if len(detail) > max_test_output:
        detail = (
            detail[:max_test_output]
            + f"\n…（失败详情过长已截断，共 {len(detail)} 字符，先修上面的用例再重跑）"
        )

    return f"{head}\n失败用例：\n{fails}\n失败详情（--tb=short）：\n{detail}"


# ---------------------------------------------------------------------------
# guarded_execute —— 护栏分发器
# ---------------------------------------------------------------------------
def guarded_execute(
    tool_name: str,
    tool_input: dict,
    workdir: str,
    *,
    test_timeout: int,
    max_result_chars: int,
    test_cmd: Optional[str] = None,
    test_python: Optional[str] = None,
) -> str:
    """loop 唯一的执行入口：把路径越界和任何异常都收敛成字符串，保证 loop 侧永远只拿到 str、见不到异常。
    """
    handlers = {
        "list_dir": list_dir,
        "read_file": read_file,
        "search": search,
        "edit_file": edit_file,
        "write_file": write_file,
        "apply_patch": apply_patch,
        "run_tests": run_tests,
    }
    # 1. 未知工具：立即拦下（防模型幻觉出不存在的工具）。
    if tool_name not in handlers:
        return f"错误：未知工具 {tool_name}"

    # 2. 分发：run_tests 额外注入 timeout；其余原样 **tool_input。
    handler = handlers[tool_name]
    kwargs = dict(tool_input)
    if tool_name == "run_tests":
        kwargs["timeout"] = test_timeout
        kwargs["test_cmd"] = test_cmd
        kwargs["test_python"] = test_python

    # 3. 异常兜底。
    try:
        result = handler(workdir, **kwargs)
    except sandbox.PathEscape:
        original = tool_input.get("path", "")
        result = f"错误：路径越界，只能访问任务工作目录内的文件：{original}"
    except (FileNotFoundError, IsADirectoryError) as e:
        result = f"错误：文件访问失败：{e}"
    except UnicodeDecodeError:
        result = "错误：无法以文本读取（疑似二进制）"
    except TypeError as e:
        result = f"错误：工具参数不合法：{e}"
    except Exception as e:
        result = f"错误：工具执行失败：{type(e).__name__}: {e}"

    # 4. 控制输出长度。
    if len(result) > max_result_chars:
        result = result[:max_result_chars] + "…（输出过长已截断）"
    return result
