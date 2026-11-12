# safe_extract：面向不可信归档的安全解压库

`safe_extract` 用 Python 标准库实现，供业务系统处理用户上传的
**ZIP、TAR、TAR.GZ** 文件。不依赖第三方包，不需要 Docker，也不提供
独立命令行或网页，只暴露可调用的 Python API。

## 安装与环境

直接把 `safe_extract/` 目录放入项目源码树即可，无第三方依赖。

- Python：3.8+（开发与测试环境为 Python 3.14，仅使用标准库）
- 平台：Linux 完整支持并已测试；macOS 等 POSIX 系统适用同一套机制；
  Windows 提供等价实现但**未在本仓库测试覆盖**，见“并发与平台说明”。

## 快速上手

```python
from safe_extract import safe_extract

result = safe_extract("/tmp/uploads/a.zip", "/var/data/job_42")
print(result.target, result.files, result.total_bytes)
```

也支持已经打开的、**可 seek 的二进制文件对象**：

```python
with open(upload_path, "rb") as handle:
    result = safe_extract(handle, destination)
```

### `safe_extract(archive, destination, *, limits=None, archive_format=None, lock_timeout=0.0)`

| 参数 | 说明 |
| --- | --- |
| `archive` | 归档文件路径，或可 seek 的二进制文件对象 |
| `destination` | 目标目录，**必须尚不存在**；已存在（含符号链接）直接报错 |
| `limits` | `ExtractionLimits` 实例，`None` 表示使用默认限制 |
| `archive_format` | 显式指定 `"zip"` / `"tar"` / `"tar.gz"`；默认按魔数自动识别 |
| `lock_timeout` | 目标锁等待秒数，`0.0` 表示抢不到锁立即失败 |

返回 `ExtractionResult(target, members, files, directories, total_bytes)`。

### 可配置限制

```python
from safe_extract import ExtractionLimits, safe_extract

limits = ExtractionLimits(
    max_members=10_000,
    max_single_file_size=10 * 1024 * 1024,
    max_total_size=100 * 1024 * 1024,
    max_path_depth=20,
)
safe_extract(archive, destination, limits=limits)
```

默认值：

| 限制 | 默认值 |
| --- | --- |
| `max_members` | 100,000 个成员 |
| `max_single_file_size` | 100 MiB |
| `max_total_size` | 1 GiB |
| `max_path_depth` | 100 层路径分量 |

所有大小限制都按**实际从数据流读出的字节**累计，不采信归档头部声明的
尺寸；一旦超限立即中止，不会等全部解压完。参数必须是非负整数，否则构造
`ExtractionLimits` 时抛出 `ValueError`。

## 错误分类

所有异常都继承自 `SafeExtractError`，并带 `member`（问题成员名）与
`path`（相关本地路径）属性，方便调用方定位与分类处理：

| 异常 | 含义 |
| --- | --- |
| `UnsafeContentError` | 不安全内容：危险路径、重名、文件/目录类型冲突、符号链接/硬链接/设备/FIFO 等 |
| `ResourceLimitError` | 超过成员数、单文件大小、总大小或路径深度限制 |
| `ArchiveCorruptError` | 归档损坏、截断、gzip/zlib 错误、ZIP CRC 校验失败等 |
| `TargetConflictError` | 目标已存在、父目录不存在、无法发布等 |
| `LockError` | 目标锁被其他解压占用（`TargetConflictError` 的子类） |

```python
from safe_extract import (
    UnsafeContentError,
    ResourceLimitError,
    ArchiveCorruptError,
    TargetConflictError,
)

try:
    safe_extract(archive, destination)
except UnsafeContentError as exc:
    log.warning("拒绝不安全成员 %s", exc.member)
except ResourceLimitError:
    ...
except ArchiveCorruptError:
    ...
except TargetConflictError:
    ...
```

## 安全边界（保证什么）

1. **路径绝不越界**。成员名先做平台无关的校验，再规范化：
   - 拒绝 `../` 之类的父目录引用、绝对路径（`/etc/...`）；
   - 在 Linux 下同样拒绝 Windows 盘符（`C:`、`C:foo`）、UNC 路径
     （`//server/share`）；
   - 拒绝包含反斜杠 `\` 或 NUL 字节的名字；
   - 规范化后重名、同一路径既当文件又当目录，明确拒绝。
2. **成员类型白名单**。TAR/ZIP 中只接受常规文件与目录；符号链接、
   硬链接、字符/块设备、FIFO、contiguous 文件等一律拒绝，因此归档无法
   在解压目录内制造链接。
3. **防父路径符号链接偏移**。所有写入路径在创建后用 `realpath`
   复核，确认真实位置仍位于临时目录内部；即使临时目录里被预先放入指向
   外部的符号链接，写入也会被拦截，目标目录外的哨兵文件不会被改动。
4. **先暂存、后原子发布**。永远不直接写最终目录：在目标的同一父目录下
   用 `tempfile.mkdtemp` 建立独立临时目录（权限 `0700`，文件 `0600`），
   全部成员校验并写入成功后，再用同目录 `os.rename` 原子改名发布。
5. **失败必清理**。任何异常（不安全内容、超限、损坏、冲突）都会删除整个
   临时目录并释放锁，不留下半成品或锁文件。
6. **目标已存在即拒绝**。发布前后两次检查目标是否存在，不会修改或覆盖
   已有目录的内容。
7. **流式限额**。逐块读取、逐块计数，单文件与总量限制在读的过程中即时
   生效，压缩炸弹（高压缩比 gzip）同样会被实际字节计数拦下。

## 并发控制与平台说明

锁文件位于目标的父目录，命名为 `<目标名>.lock`，协议如下：

- 用 `O_CREAT | O_EXCL` 原子创建锁文件，保证“先到先得”；同一目标的
  并发调用只有一个能进入临界区，其余立即（或等待 `lock_timeout` 后）
  抛出 `LockError`，已发布的结果不会被覆盖。
- **POSIX（Linux/macOS 等）**：额外对锁文件加 `flock(2)` 建议锁。进程
  退出（包括崩溃、被 `SIGKILL`）时内核自动释放 `flock`；对遗留锁文件，
  再结合文件内记录的 PID 用 `kill(pid, 0)` 判断持有者是否已死，死锁可
  被后到者接管。测试覆盖了多线程、多子进程竞争与陈旧锁接管。
- **生效条件**：竞争方必须在**同一台机器、同一个文件系统**上工作，
  因为 `O_EXCL` 与 `flock` 都是本机文件系统语义；网络文件系统
  （NFS 等）上 `flock`/原子创建的语义取决于挂载与服务端配置，不在保证
  范围内。
- **Windows**：代码保留了基于 `msvcrt.locking` 的等价回退路径，但
  PID 探活无法覆盖其他用户的进程，且该路径**没有在本仓库的 CI 测试中
  验证**；生产使用前请在目标 Windows 环境自行验证。

## 安全边界之外（不保证什么）

- 不做病毒/恶意内容查杀，只保证文件不会逃出目标目录、类型受控、限额
  生效；解压后的文件仍应按不可信数据对待。
- 不保留归档里记录的属主、权限位、修改时间等元数据；目录统一 `0700`、
  文件统一 `0600`。
- 不支持加密 ZIP（遇到加密条目抛出 `UnsafeContentError`）、ZIP 分卷、
  符号链接解压等场景。
- 不限制压缩比本身、不限制内存中的文件名长度以外的字符串处理；调用方
  仍应配合磁盘配额与上游请求大小限制使用。
- Windows 专属保留名（如 `CON`、`PRN`）未额外拦截；本库主要面向
  Linux 服务端场景。

## 目录结构

```
safe_extract/
  __init__.py      # 公共 API 与异常导出
  constants.py     # 格式标识
  engine.py        # 编排：锁、暂存目录、原子发布、清理
  errors.py        # 四类异常 + 锁异常
  limits.py        # ExtractionLimits
  lock.py          # 跨进程目标锁
  paths.py         # 成员名校验、路径包含判断
  result.py        # ExtractionResult
  tar_archive.py   # TAR / TAR.GZ 流式消费者
  tracker.py       # 成员/类型冲突跟踪、流式写入与限额
  zip_archive.py   # ZIP 流式消费者
tests/             # unittest 用例，全部在临时目录离线运行
```

## 运行测试

```bash
python3 -m unittest discover -s tests -v
```

测试全部用 `tempfile.mkdtemp` 动态生成正常与恶意归档，不读取或修改任何
真实用户文件，离线运行。覆盖内容包括：

- 三种格式的正常解压、文件对象输入、格式自动识别；
- `../`、绝对路径、UNC、Windows 盘符、反斜杠、NUL、重名、文件/目录
  类型冲突；
- TAR 符号链接/硬链接/字符设备/块设备/FIFO、ZIP 符号链接/FIFO 拒绝；
- 成员数、单文件、总量、深度限制，以及伪造头部声明超大尺寸；
- ZIP CRC 失败、ZIP/TAR/TAR.GZ 截断、随机字节、错误成员定位；
- 目标已存在/为符号链接/父目录缺失、失败后无残留、外部哨兵未被修改；
- 8 线程与 4 子进程并发只有一个成功、锁超时等待、陈旧锁接管。

## 已知限制与未验证项

- Windows 上的 `msvcrt.locking` 路径未实际测试（开发环境为 Linux）。
- 网络文件系统上的锁语义未验证，仅保证本机同文件系统。
- 仅在 CPython 3.14 上实际运行测试；代码按 3.8+ 语法编写但未在旧版本
  逐一验证。
