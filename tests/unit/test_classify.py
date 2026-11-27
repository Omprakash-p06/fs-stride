"""UT-10: knee estimation and configuration classification."""

from __future__ import annotations

import logging

import pytest
from fs_stride_analysis.classify import classify_config, knee


def test_knee_flat():
    assert knee({}) == (None, "flat")
    assert knee({8: False, 16: False, 32: False}) == (None, "flat")


@pytest.mark.parametrize(
    ("contended", "expected"),
    [
        ({8: True, 16: True, 32: True, 64: False, 128: False}, (64, "line64")),
        ({8: True, 16: True, 32: True, 64: True, 128: False}, (128, "pair128")),
        ({8: True, 16: True, 32: True, 64: True, 128: True}, (256, "wider")),
        ({8: False, 16: False, 32: False, 64: False, 128: True}, (None, "irregular")),
        ({8: True, 16: False, 32: True, 64: False, 128: False}, (None, "irregular")),
    ],
)
def test_knee_classes(contended, expected):
    assert knee(contended) == expected


def _summary(
    mde90: float, contended: dict[int, bool], faster_wider=None, single_thread=False
):
    return {
        "mde90": mde90,
        "contended": contended,
        "faster_wider": faster_wider or [],
        "single_thread": single_thread,
    }


def test_classify_inconclusive_gate():
    cls, knee_bytes, gate, reason = classify_config(_summary(0.20, {8: True}))
    assert (cls, knee_bytes, gate) == ("inconclusive", None, "inconclusive")
    assert reason and "mde90" in reason


def test_classify_strict_h1_gate():
    assert classify_config(_summary(0.07, {8: True}), gate=0.05)[0] == "inconclusive"
    assert classify_config(_summary(0.07, {8: False}), gate=0.10)[0] == "flat"


def test_classify_faster_wider_is_irregular(caplog):
    summary = _summary(
        0.0, {8: False}, faster_wider=[{"stride": 512, "effect_pct": -5.0}]
    )
    with caplog.at_level(logging.WARNING, logger="fs_stride_analysis.classify"):
        cls, knee_bytes, gate, reason = classify_config(summary)
    assert (cls, knee_bytes, gate) == ("irregular", None, "pass")
    assert reason and "faster-wider" in reason
    assert "faster-wider detected at stride 512" in caplog.text


def test_classify_normal_knee():
    cls, knee_bytes, gate, reason = classify_config(
        _summary(0.0, {8: True, 16: False, 32: False})
    )
    assert (cls, knee_bytes, gate, reason) == ("line64", 16, "pass", None)


def test_classify_single_thread_hides_knee(caplog):
    with caplog.at_level(logging.WARNING, logger="fs_stride_analysis.classify"):
        cls, knee_bytes, gate, reason = classify_config(
            _summary(0.0, {8: True, 16: False}, single_thread=True)
        )
    assert (cls, knee_bytes, gate) == ("line64", None, "pass")
    assert reason == "single-thread baseline only"
    assert "threads=1 only" in caplog.text
