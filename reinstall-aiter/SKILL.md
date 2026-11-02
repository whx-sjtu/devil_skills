---
name: reinstall-aiter
description: Cleanly reinstall aiter from source after switching its git version or editing its code, clearing stale JIT .so files and build artifacts. Use when the user asks to reinstall or rebuild aiter, or to make a checkout or code change in aiter take effect.
---

# 重装 aiter

切换 aiter 代码版本或改动代码后，从源码干净重装，避免旧安装、旧 JIT `.so` 和旧构建产物混进新版本。

## 1. 定位源码目录

使用用户给的 aiter 源码目录；未指定时用 `/app/aiter`。需要切换版本时，先在该目录完成 checkout，再重装。

## 2. 重装

把 `<AITER_DIR>` 换成源码目录后执行。`GPU_ARCHS` 默认 `gfx950`，用户指定其他架构时替换。

```bash
(
set -e
cd <AITER_DIR>
test -d aiter/jit  # 确认位于 aiter 源码根目录，再执行下面的 rm -rf
pip uninstall -y aiter amd-aiter

git submodule sync
git submodule update --init --recursive

rm -rf ./aiter/jit/*.so
rm -rf aiter/install_mode
rm -rf ./dist/
rm -rf ./build

AITER_USE_SYSTEM_TRITON=1 GPU_ARCHS=gfx950 python3 setup.py install
)
```

- 分发名从 aiter #1620 起是 `amd-aiter`，更早的版本是 `aiter`，所以两个名字都要卸；未安装的那个 pip 只打 warning，退出码为 0。
- `AITER_USE_SYSTEM_TRITON=1` 用于保留环境里现有的 triton。不加时，torch ≥ 2.9.1 下 `setup.py` 会卸掉现有 triton，换装 aiter 自带的版本。
- 编译耗时较长：放后台运行，跟踪输出直到命令结束，以退出码判断成败。

## 3. 验收

```bash
pip list 2>/dev/null | grep -i aiter
git -C <AITER_DIR> rev-parse --short HEAD
```

完成标准：安装命令退出码为 0；`pip list` 只有一条 aiter 记录，版本号中 `+g` 后的 hash 以当前 HEAD 开头。
