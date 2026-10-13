"""Minimal TensorRT 8.5 runner (Python API + ctypes CUDA runtime; no pycuda/cuda-python needed).

Runs inside the DeepStream 6.3 container (TensorRT 8.5.2.2, CUDA 11.4):

    from trt_runner import TrtRunner
    run = TrtRunner("engine_cache/<name>.engine")
    out = run(batch_nchw_float32)          # -> (B, 52, 18900) float32
"""
from __future__ import annotations

import ctypes
import glob
import time

import numpy as np
import tensorrt as trt

_H2D, _D2H = 1, 2


def _cudart():
    for pat in ("/usr/local/cuda/lib64/libcudart.so*", "/usr/local/cuda/targets/aarch64-linux/lib/libcudart.so*",
                "/usr/lib/aarch64-linux-gnu/libcudart.so*"):
        for path in sorted(glob.glob(pat)):
            try:
                return ctypes.CDLL(path)
            except OSError:
                continue
    raise OSError("libcudart not found")


class TrtRunner:
    def __init__(self, engine_path, logger_level=trt.Logger.WARNING):
        self.cuda = _cudart()
        self.cuda.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
        self.cuda.cudaMemcpy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self.cuda.cudaFree.argtypes = [ctypes.c_void_p]
        logger = trt.Logger(logger_level)
        trt.init_libnvinfer_plugins(logger, "")
        with open(engine_path, "rb") as f:
            self.engine = trt.Runtime(logger).deserialize_cuda_engine(f.read())
        self.ctx = self.engine.create_execution_context()
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.inp = next(n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT)
        self.out = next(n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT)
        prof = self.engine.get_profile_shape(0, self.inp)  # (min, opt, max)
        self.min_batch, self.opt_batch, self.max_batch = prof[0][0], prof[1][0], prof[2][0]
        self._bufs = {}
        self.last_ms = 0.0

    def _buf(self, name, nbytes):
        ptr, size = self._bufs.get(name, (None, 0))
        if size < nbytes:
            if ptr is not None:
                self.cuda.cudaFree(ptr)
            ptr = ctypes.c_void_p()
            if self.cuda.cudaMalloc(ctypes.byref(ptr), nbytes) != 0:
                raise MemoryError(f"cudaMalloc {nbytes} B failed")
            self._bufs[name] = (ptr, nbytes)
        return self._bufs[name][0]

    def __call__(self, x: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(x, dtype=np.float32)
        if not self.min_batch <= x.shape[0] <= self.max_batch:
            raise ValueError(f"batch {x.shape[0]} outside the engine profile {self.min_batch}..{self.max_batch}")
        self.ctx.set_input_shape(self.inp, tuple(x.shape))
        out_shape = tuple(self.ctx.get_tensor_shape(self.out))
        y = np.empty(out_shape, np.float32)
        din, dout = self._buf("in", x.nbytes), self._buf("out", y.nbytes)
        self.ctx.set_tensor_address(self.inp, din.value)
        self.ctx.set_tensor_address(self.out, dout.value)
        t = time.perf_counter()
        self.cuda.cudaMemcpy(din, x.ctypes.data, x.nbytes, _H2D)
        if not self.ctx.execute_async_v3(0):
            raise RuntimeError("TensorRT execution failed")
        self.cuda.cudaMemcpy(y.ctypes.data, dout, y.nbytes, _D2H)  # synchronous on the default stream
        self.last_ms = (time.perf_counter() - t) * 1000
        return y

    def __del__(self):
        for ptr, _ in getattr(self, "_bufs", {}).values():
            try:
                self.cuda.cudaFree(ptr)
            except Exception:
                pass
