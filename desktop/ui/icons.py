from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _pix(size: int = 20) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor("#263238"), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return pix, painter


def eye_icon() -> QIcon:
    pix, painter = _pix(20)
    path = QPainterPath()
    path.moveTo(2, 10)
    path.cubicTo(6, 4, 14, 4, 18, 10)
    path.cubicTo(14, 16, 6, 16, 2, 10)
    painter.drawPath(path)
    painter.drawEllipse(QRectF(8, 8, 4, 4))
    painter.end()
    return QIcon(pix)


def flag_icon() -> QIcon:
    pix, painter = _pix(16)
    painter.setPen(QPen(QColor("#1f5e93"), 1.4))
    painter.drawLine(QPointF(4, 2), QPointF(4, 14))
    path = QPainterPath()
    path.moveTo(4, 2.5)
    path.lineTo(13, 5.5)
    path.lineTo(4, 8.5)
    path.closeSubpath()
    painter.fillPath(path, QColor("#1f5e93"))
    painter.end()
    return QIcon(pix)


def pencil_icon() -> QIcon:
    pix, painter = _pix(20)
    painter.drawLine(4, 14, 16, 4)
    painter.drawLine(16, 4, 18, 6)
    painter.drawLine(18, 6, 6, 16)
    painter.drawLine(4, 14, 3, 17)
    painter.drawLine(3, 17, 6, 16)
    painter.end()
    return QIcon(pix)


def _history_pixmap(color: QColor, mirror: bool, dpr: int) -> QPixmap:
    logical = 24
    pix = QPixmap(logical * dpr, logical * dpr)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if mirror:
        painter.translate(logical, 0)
        painter.scale(-1, 1)
    painter.translate(2.2, 2.4)
    painter.scale(1.22, 1.22)
    pen = QPen(color, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(4.4, 6.5)
    path.lineTo(10.0, 6.5)
    path.arcTo(QRectF(6.5, 6.5, 7.0, 7.0), 90, -180)
    path.lineTo(8.4, 13.5)
    painter.drawPath(path)
    tip = QPointF(4.4, 6.5)
    painter.drawLine(tip, QPointF(7.6, 3.5))
    painter.drawLine(tip, QPointF(7.6, 9.5))
    painter.end()
    return pix


def _history_icon(mirror: bool) -> QIcon:
    icon = QIcon()
    colors = (
        (QIcon.Mode.Normal, QColor("#263238")),
        (QIcon.Mode.Active, QColor("#1f5e93")),
        (QIcon.Mode.Disabled, QColor("#9aabb8")),
    )
    for dpr in (1, 2):
        for mode, color in colors:
            icon.addPixmap(_history_pixmap(color, mirror, dpr), mode, QIcon.State.Off)
    return icon


def undo_icon() -> QIcon:
    return _history_icon(False)


def redo_icon() -> QIcon:
    return _history_icon(True)
