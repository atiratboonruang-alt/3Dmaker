import os

import pytest

from maker3d.export import export_part
from maker3d.model import FEATURE_TYPES, Document, Feature, part_info, rebuild


def test_every_feature_type_builds_on_a_box():
    for type_id, ft in FEATURE_TYPES.items():
        if type_id == "import_step":
            continue
        base = Feature.new("box", length=60, width=60, height=30)
        feat = Feature.new(type_id)
        if ft.category == "body":
            feat.params["mode"] = "add"
        part, _ = rebuild([base, feat])
        assert feat.error is None, f"{type_id}: {feat.error}"
        assert part.volume > 0


def test_hole_cuts_material():
    box = Feature.new("box", length=20, width=20, height=10)
    hole = Feature.new("hole", diameter=6, depth=50, z=10)
    whole, _ = rebuild([box])
    cut, _ = rebuild([box, hole])
    assert cut.volume < whole.volume


def test_pattern_grid():
    f = Feature.new("cylinder", radius=2, height=5, pattern="grid", count_x=3, count_y=2, spacing_x=10, spacing_y=10)
    part, _ = rebuild([f])
    single, _ = rebuild([Feature.new("cylinder", radius=2, height=5)])
    assert part.volume == pytest.approx(single.volume * 6, rel=1e-3)


def test_error_is_reported_and_part_kept():
    box = Feature.new("box")
    bad = Feature.new("fillet", radius=500)
    part, _ = rebuild([box, bad])
    assert bad.error
    assert part is not None and part.volume > 0


def test_info():
    part, _ = rebuild([Feature.new("box", length=10, width=10, height=10)])
    info = part_info(part)
    assert info["volume_cm3"] == pytest.approx(1.0)
    assert info["size"] == pytest.approx((10, 10, 10))


def test_undo_redo_and_save(tmp_path):
    doc = Document()
    doc.add("box")
    doc.add("hole")
    assert len(doc.features) == 2
    doc.undo()
    assert len(doc.features) == 1
    doc.redo()
    assert len(doc.features) == 2
    path = tmp_path / "p.3dmk"
    doc.save(str(path))
    doc2 = Document()
    doc2.load(str(path))
    assert [f.to_dict() for f in doc2.features] == [f.to_dict() for f in doc.features]


@pytest.mark.parametrize("ext", ["stl", "3mf", "step"])
def test_export(tmp_path, ext):
    part, _ = rebuild([Feature.new("box")])
    out = export_part(part, str(tmp_path / f"o.{ext}"))
    assert os.path.getsize(out) > 0
