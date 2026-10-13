"""tools/check_model.py: exits non-zero on every kind of mismatch (M1 acceptance)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "reader"))

import check_model as cm  # noqa: E402
from lpr_reader import classes as C  # noqa: E402

GOOD_JSON = {"names": {str(i): n for i, n in enumerate(C.CLASS_NAMES)},
             "char_glyphs": {str(k): v for k, v in C.GLYPHS.items()}}


def tiny_onnx(path: Path, out_shape=(1, 52, 18900), names=None):
    """Stand-in model: input images[1,3,960,960] -> constant 0.5 tensor of out_shape (no weights needed)."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    shape = helper.make_tensor("shape", TensorProto.INT64, [len(out_shape)], list(out_shape))
    value = helper.make_tensor("value", TensorProto.FLOAT, [1], [0.5])
    node = helper.make_node("ConstantOfShape", ["shape"], ["output0"], value=value)
    graph = helper.make_graph(
        [node], "tiny",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 960, 960])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(out_shape))],
        initializer=[shape])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    meta = model.metadata_props.add()
    meta.key, meta.value = "names", str(dict(enumerate(names or C.CLASS_NAMES)))
    onnx.save(model, str(path))


def make_dir(tmp_path: Path, class_json=None, onnx_shape=(1, 52, 18900), with_onnx=True, init=True) -> Path:
    d = tmp_path / "vX"
    d.mkdir()
    (d / "m_best.pt").write_bytes(b"not really weights")
    (d / "class_names.json").write_text(json.dumps(class_json or GOOD_JSON, ensure_ascii=False), encoding="utf-8")
    if with_onnx:
        tiny_onnx(d / "m_best.onnx", onnx_shape)
    if init:
        assert cm.main([str(d), "--init-sums"]) == 0
    return d


def run(d: Path, *extra) -> int:
    return cm.main([str(d), "--agents-md", str(REPO / "AGENTS.md"), *extra])


def test_good_dir_passes_and_writes_labels(tmp_path):
    d = make_dir(tmp_path)
    assert run(d) == cm.EXIT_OK
    assert (d / "labels.txt").read_text(encoding="utf-8").splitlines() == list(C.CLASS_NAMES)


def test_wrong_mapping_fails(tmp_path, capsys):
    """Deliberately wrong mapping: Sin and Sad swapped, with checksums regenerated so only the mapping is wrong."""
    bad = json.loads(json.dumps(GOOD_JSON))
    bad["names"]["16"], bad["names"]["18"] = "Sad", "Sin"
    d = make_dir(tmp_path, class_json=bad, with_onnx=False)
    assert run(d, "--skip-onnx") == cm.EXIT_CLASSES
    out = capsys.readouterr().out
    assert "id 16: got 'Sad', expected 'Sin'" in out
    assert not (d / "labels.txt").exists()


@pytest.mark.parametrize("mutate", [
    lambda n: n.pop("47"),                    # missing class
    lambda n: n.update({"48": "extra"}),      # extra class
    lambda n: n.update({"30": "Plate"}),      # renamed
])
def test_other_mapping_errors_fail(tmp_path, mutate):
    bad = json.loads(json.dumps(GOOD_JSON))
    mutate(bad["names"])
    d = make_dir(tmp_path, class_json=bad, with_onnx=False)
    assert run(d, "--skip-onnx") == cm.EXIT_CLASSES


def test_wrong_glyph_fails(tmp_path):
    bad = json.loads(json.dumps(GOOD_JSON))
    bad["char_glyphs"]["16"] = "ص"
    d = make_dir(tmp_path, class_json=bad, with_onnx=False)
    assert run(d, "--skip-onnx") == cm.EXIT_CLASSES


def test_flat_class_names_format_accepted(tmp_path):
    d = make_dir(tmp_path, class_json=GOOD_JSON["names"], with_onnx=False)
    assert run(d, "--skip-onnx") == cm.EXIT_OK


def test_tampered_file_fails(tmp_path):
    d = make_dir(tmp_path, with_onnx=False)
    (d / "m_best.pt").write_bytes(b"changed weights")
    assert run(d, "--skip-onnx") == cm.EXIT_SUMS


def test_missing_sums_fails(tmp_path):
    d = make_dir(tmp_path, with_onnx=False, init=False)
    assert run(d, "--skip-onnx") == cm.EXIT_SUMS


def test_unlisted_model_file_fails(tmp_path):
    d = make_dir(tmp_path, with_onnx=False)
    (d / "other.pt").write_bytes(b"x")
    assert run(d, "--skip-onnx") == cm.EXIT_SUMS


def test_listed_file_missing_fails(tmp_path):
    d = make_dir(tmp_path, with_onnx=False)
    (d / "m_best.pt").unlink()
    assert run(d, "--skip-onnx") == cm.EXIT_SUMS


def test_init_sums_never_overwrites(tmp_path):
    d = make_dir(tmp_path, with_onnx=False)
    before = (d / "SHA256SUMS").read_text()
    assert cm.main([str(d), "--init-sums"]) == cm.EXIT_SUMS
    assert (d / "SHA256SUMS").read_text() == before


def test_agents_md_drift_fails(tmp_path):
    d = make_dir(tmp_path, with_onnx=False)
    md = tmp_path / "AGENTS.md"
    md.write_text((REPO / "AGENTS.md").read_text(encoding="utf-8").replace("| 30 | `plate` |", "| 30 | `plates` |"),
                  encoding="utf-8")
    assert cm.main([str(d), "--agents-md", str(md), "--skip-onnx"]) == cm.EXIT_CLASSES


def test_wrong_onnx_output_shape_fails(tmp_path):
    pytest.importorskip("onnxruntime")
    d = make_dir(tmp_path, onnx_shape=(1, 52, 8400))
    assert run(d) == cm.EXIT_ONNX


def test_onnx_metadata_names_mismatch_fails(tmp_path):
    pytest.importorskip("onnxruntime")
    d = make_dir(tmp_path, with_onnx=False, init=False)
    names = list(C.CLASS_NAMES)
    names[16], names[18] = names[18], names[16]
    tiny_onnx(d / "m_best.onnx", names=names)
    assert cm.main([str(d), "--init-sums"]) == 0
    assert run(d) == cm.EXIT_ONNX


@pytest.mark.parametrize("ver", ["v1", "v2"])
def test_delivered_models(ver, tmp_path):
    """The real model folders (skipped when the git-ignored weights are absent)."""
    d = REPO / "models" / ver
    if not (d / "SHA256SUMS").exists() or not list(d.glob("*.onnx")):
        pytest.skip(f"models/{ver} not present")
    pytest.importorskip("onnxruntime")
    assert cm.main([str(d), "--labels-out", str(tmp_path / "labels.txt"), "--no-run"]) == cm.EXIT_OK
