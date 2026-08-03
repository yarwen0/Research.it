"""The chart payload contract shared by the backend and the React charts.

Every trend the backend produces is shaped by create_chart_response, so the
frontend renders one structure regardless of which analysis emitted it.
"""

from __future__ import annotations

from typing import Any, Literal

ChartType = Literal["line", "bar", "pie", "scatter", "area", "radar", "heatmap", "sankey", "wordcloud"]
LayoutType = Literal["horizontal", "vertical"]


def create_chart_response(
    chart_type: ChartType,
    title: str,
    description: str,
    data_points: list[dict[str, Any]],
    series: list[dict[str, Any]],
    x_axis_label: str | None = None,
    y_axis_label: str | None = None,
    layout: LayoutType | None = None,
    stacked: bool = False
) -> dict[str, Any]:
    """
    Create a standardized chart response structure.
    
    Args:
        chart_type: Type of chart (line, bar, pie, etc.)
        title: Chart title
        description: Chart description
        data_points: List of data points, each with id, label, and values
        series: List of series configurations
        x_axis_label: Label for X axis
        y_axis_label: Label for Y axis
        layout: Chart layout orientation
        stacked: Whether to stack series
        
    Returns:
        Standardized chart data structure
    """
    return {
        "config": {
            "type": chart_type,
            "title": title,
            "description": description,
            "xAxisLabel": x_axis_label,
            "yAxisLabel": y_axis_label,
            "layout": layout,
            "stacked": stacked
        },
        "dataPoints": data_points,
        "series": series
    }
