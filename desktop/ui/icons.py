from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
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


def pencil_icon() -> QIcon:
    pix, painter = _pix(20)
    painter.drawLine(4, 14, 16, 4)
    painter.drawLine(16, 4, 18, 6)
    painter.drawLine(18, 6, 6, 16)
    painter.drawLine(4, 14, 3, 17)
    painter.drawLine(3, 17, 6, 16)
    painter.end()
    return QIcon(pix)


def undo_icon() -> QIcon:
    pix, painter = _pix(16)
    painter.drawArc(QRectF(4, 4, 9, 9), 40 * 16, 220 * 16)
    painter.drawLine(4, 7, 7, 4)
    painter.drawLine(4, 7, 7, 10)
    painter.end()
    return QIcon(pix)


def redo_icon() -> QIcon:
    pix, painter = _pix(16)
    painter.drawArc(QRectF(3, 4, 9, 9), -80 * 16, 220 * 16)
    painter.drawLine(12, 7, 9, 4)
    painter.drawLine(12, 7, 9, 10)
    painter.end()
    return QIcon(pix)
