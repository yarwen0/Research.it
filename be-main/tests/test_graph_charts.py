"""Tests for chart response helpers in utils.graph."""

from utils.graph import create_chart_response


def test_create_chart_response_shape():
    result = create_chart_response(
        chart_type="bar",
        title="Papers per Year",
        description="Publication counts over time",
        data_points=[{"id": "2024", "label": "2024", "value": 3}],
        series=[{"key": "count", "label": "Papers"}],
        x_axis_label="Year",
        y_axis_label="Count",
        layout="vertical",
        stacked=True,
    )

    assert result["config"]["type"] == "bar"
    assert result["config"]["title"] == "Papers per Year"
    assert result["config"]["xAxisLabel"] == "Year"
    assert result["config"]["stacked"] is True
    assert result["dataPoints"] == [{"id": "2024", "label": "2024", "value": 3}]
    assert result["series"] == [{"key": "count", "label": "Papers"}]
