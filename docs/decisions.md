# Decisions

Format: date, decision, reason, alternatives, source.

## 2026-10-13: Platform baseline taken from the device, not assumed

- **Decision:** Target JetPack 5.1.2 (L4T 35.4.1), CUDA 11.4, TensorRT 8.5.2, DeepStream 6.3 on Jetson Xavier NX 8 GB.
  This is the A.7 Xavier path (JetPack 5.1.x → DeepStream 6.3 / TensorRT 8.5).
- **Reason:** Read from the device: `/etc/nv_tegra_release` (R35.4.1), `dpkg -l` (nvidia-l4t-core 35.4.1,
  tensorrt 8.5.2.2, deepstream-6.3 6.3.0-1).
- **Alternatives:** none. Changing JetPack is not allowed without approval (A.2.2).
- **Source:** device output (see STATUS.md); the container tag gets verified against NGC and the DeepStream 6.3
  release notes in M3.

## 2026-10-13: Part A of CLAUDE.md is the AGENTS.md rulebook

- **Decision:** Treat Part A of the existing `CLAUDE.md` as `AGENTS.md` until the user decides on the file split.
- **Reason:** `AGENTS.md` does not exist; `CLAUDE.md` contains Part A + Part B verbatim.
- **Alternatives:** create `AGENTS.md` from Part A (proposed in the M0 questions).
- **Source:** repo inspection.

## 2026-10-13: Large model files stay out of git

- **Decision:** `.pt`, `.onnx` and `.engine` files are git-ignored; `SHA256SUMS` will be committed.
- **Reason:** A.2.6, A.8.
- **Source:** AGENTS.md.
