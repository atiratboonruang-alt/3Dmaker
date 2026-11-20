import os

import pytest

from maker3d.export import export_part
from build123d import Axis

from maker3d.model import (FEATURE_TYPES, Document, Feature, edge_ref, face_ref, get_path, part_info, rebuild,
                           set_path)


def test_every_feature_type_builds_on_a_box():
    for type_id, ft in FEATURE_TYPES.items():
        if type_id in ("import_step", "sketch", "pull", "pushpull"):
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


def _box_top_sketch(shapes):
    box = Feature.new("box", length=40, width=40, height=10)
    sk = Feature.new("sketch", origin=[0, 0, 10], normal=[0, 0, 1], shapes=shapes)
    return box, sk


def test_sketch_circle_pull_down_makes_hole():
    box, sk = _box_top_sketch([{"kind": "circle", "c": [5, 5], "r": 3}])
    pull = Feature.new("pull", sketch=sk.uid, shapes=[0], distance=-4)
    full, _ = rebuild([box])
    part, tools = rebuild([box, sk, pull])
    assert pull.error is None, pull.error
    assert part.volume == pytest.approx(full.volume - 3.14159265 * 9 * 4, rel=1e-4)
    assert tools[2] is not None


def test_sketch_through_and_pull_up():
    box, sk = _box_top_sketch([{"kind": "rect", "c": [0, 0], "w": 10, "h": 10},
                               {"kind": "poly", "pts": [[12, 12], [18, 12], [15, 18]]}])
    up = Feature.new("pull", sketch=sk.uid, shapes=[0], distance=5)
    thru = Feature.new("pull", sketch=sk.uid, shapes=[1], distance=-1, through=True)
    part, _ = rebuild([box, sk, up, thru])
    assert up.error is None and thru.error is None
    assert part.bounding_box().size.Z == pytest.approx(15)
    assert part.volume == pytest.approx(40 * 40 * 10 + 500 - 18 * 10, rel=1e-4)


def test_pushpull_face_and_picked_fillet_and_shell():
    box = Feature.new("box", length=20, width=20, height=10)
    part, _ = rebuild([box])
    top = part.faces().sort_by(Axis.Z)[-1]
    pp = Feature.new("pushpull", face_refs=[face_ref(top)], distance=5)
    part2, _ = rebuild([box, pp])
    assert part2.bounding_box().size.Z == pytest.approx(15)
    # edge picked on the original box still found after the face moved up
    e = part2.edges().group_by(Axis.Z)[-1][0]
    fil = Feature.new("fillet", edges="picked", edge_refs=[edge_ref(e)], radius=1)
    top2 = part2.faces().sort_by(Axis.Z)[-1]
    sh = Feature.new("shell", opening="picked", face_refs=[face_ref(top2)], thickness=1)
    part3, _ = rebuild([box, pp, fil, sh])
    assert fil.error is None and sh.error is None, (fil.error, sh.error)
    assert part3.volume < part2.volume


def test_missing_sketch_reports_error():
    box = Feature.new("box")
    pull = Feature.new("pull", sketch="nope", shapes=[0])
    part, _ = rebuild([box, pull])
    assert pull.error and part is not None


def test_dotted_paths():
    p = {"shapes": [{"kind": "circle", "c": [1, 2], "r": 3}, {"kind": "poly", "pts": []}]}
    assert get_path(p, "shapes.0.c.1") == 2
    set_path(p, "shapes.0.r", 7)
    set_path(p, "shapes.1.pts", "0,0; 1,0; 0,1")
    assert p["shapes"][0]["r"] == 7 and p["shapes"][1]["pts"] == [[0, 0], [1, 0], [0, 1]]


def test_add_shape_merges_coplanar_and_delete_fixes_pulls():
    doc = Document()
    doc.add("box", length=40, width=40, height=10)
    sk, i0 = doc.add_sketch_shape({"origin": [0, 0, 10], "normal": [0, 0, 1]},
                                  {"kind": "circle", "c": [0, 0], "r": 2})
    sk2, i1 = doc.add_sketch_shape({"origin": [5, 0, 10], "normal": [0, 0, 1]},
                                   {"kind": "circle", "c": [1, 0], "r": 2})
    assert sk is sk2 and (i0, i1) == (0, 1)
    assert sk.params["shapes"][1]["c"] == [6, 0]
    doc.add("pull", sketch=sk.uid, shapes=[1], distance=-3)
    doc.delete_shapes(sk.uid, [0])
    pull = doc.features[-1]
    assert pull.params["shapes"] == [0]
    part, _ = rebuild(doc.features)
    assert pull.error is None
