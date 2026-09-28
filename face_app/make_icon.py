"""Draws AppIcon.png (1024x1024): a frosted-glass masquerade mask over glowing colour.
One eyehole has a glowing eye looking out, the other is a keyhole with light shining through."""
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QRadialGradient, QTransform,
)

S = 1024
CX = S / 2
SCALE = 0.8  # mask is drawn large, then shrunk into the tile
PLACE = np.float32([[SCALE, 0, CX * (1 - SCALE)], [0, SCALE, 470 - SCALE * 520]])

app = QGuiApplication(sys.argv)


def canvas():
    img = QImage(S, S, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return img, p


def render(draw, place=False):
    """Runs draw(painter) on a blank canvas; returns premultiplied BGRA floats."""
    img, p = canvas()
    draw(p)
    p.end()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(S, S, 4).astype(np.float32)
    return cv2.warpAffine(arr, PLACE, (S, S), flags=cv2.INTER_AREA) if place else arr


def over(top, bottom):
    return top + bottom * (1 - top[..., 3:4] / 255.0)


def mask_half():
    p = QPainterPath()
    p.moveTo(CX - 2, 452)
    p.cubicTo(CX + 90, 404, CX + 210, 400, CX + 300, 350)
    p.cubicTo(CX + 350, 322, CX + 382, 300, CX + 392, 272)
    p.cubicTo(CX + 420, 360, CX + 380, 470, CX + 330, 540)
    p.cubicTo(CX + 270, 628, CX + 160, 660, CX + 92, 624)
    p.cubicTo(CX + 56, 606, CX + 34, 572, CX + 20, 560)
    p.cubicTo(CX + 10, 552, CX, 552, CX - 2, 552)
    p.closeSubpath()
    return p


def almond(cx, cy, w, h, tilt):
    p = QPainterPath()
    p.moveTo(-w / 2, 0)
    p.cubicTo(-w / 4, -h * 0.72, w / 4, -h * 0.72, w / 2, 0)
    p.cubicTo(w / 4, h * 0.62, -w / 4, h * 0.62, -w / 2, 0)
    t = QTransform()
    t.translate(cx, cy)
    t.rotate(tilt)
    return t.map(p)


def keyhole(cx, cy, k):
    p = QPainterPath()
    p.addEllipse(QPointF(cx, cy - 12 * k), 17 * k, 17 * k)
    body = QPainterPath()
    body.moveTo(cx - 7 * k, cy - 4 * k)
    body.lineTo(cx + 7 * k, cy - 4 * k)
    body.lineTo(cx + 13 * k, cy + 30 * k)
    body.lineTo(cx - 13 * k, cy + 30 * k)
    body.closeSubpath()
    return p.united(body)


def sparkle(p, x, y, r, alpha):
    star = QPainterPath()
    star.moveTo(x, y - r)
    star.quadTo(x, y, x + r, y)
    star.quadTo(x, y, x, y + r)
    star.quadTo(x, y, x - r, y)
    star.quadTo(x, y, x, y - r)
    p.fillPath(star, QColor(255, 255, 255, alpha))


tile = QPainterPath()
tile.addRoundedRect(QRectF(100, 100, 824, 824), 185, 185)
half = mask_half()
mask = half.united(QTransform(-1, 0, 0, 1, 2 * CX, 0).map(half))
LEFT_EYE, RIGHT_EYE = (CX - 150, 486), (CX + 150, 486)
left_eye = almond(*LEFT_EYE, 178, 100, 8)
right_eye = almond(*RIGHT_EYE, 178, 100, -8)
glass_shape = mask.subtracted(left_eye).subtracted(right_eye)


# 1. Background: colour blobs on deep indigo.
def draw_background(p):
    p.fillPath(tile, QColor("#0b0620"))
    p.setClipPath(tile)
    for x, y, r, color in ((290, 300, 460, "#ff2fb4"), (800, 250, 360, "#ff9a3d"),
                           (790, 760, 470, "#20d8ff"), (260, 800, 420, "#7b3dff"),
                           (520, 470, 230, "#ff5fd2")):
        g = QRadialGradient(QPointF(x, y), r)
        c = QColor(color)
        c.setAlpha(210)
        g.setColorAt(0, c)
        c.setAlpha(0)
        g.setColorAt(1, c)
        p.fillRect(QRectF(0, 0, S, S), g)


background = render(draw_background)
tile_alpha = background[..., 3:4] / 255.0
blurred = cv2.GaussianBlur(background, (0, 0), 26)


# 2. Glass body: blurred background, bent at the edges like thick glass, then frosted.
def draw_glass_shape(p):
    p.fillPath(glass_shape, QColor("white"))
    p.setPen(QPen(QColor("white"), 26, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(CX + 300, 560), QPointF(CX + 380, 930))  # handle
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(CX + 382, 938), 30, 30)


A = render(draw_glass_shape, place=True)[..., 3] / 255.0
inside = (A > 0.5).astype(np.uint8)
dist = cv2.GaussianBlur(cv2.distanceTransform(inside, cv2.DIST_L2, 5), (0, 0), 3)
gx = cv2.Sobel(dist, cv2.CV_32F, 1, 0, ksize=5)
gy = cv2.Sobel(dist, cv2.CV_32F, 0, 1, ksize=5)
norm = np.sqrt(gx ** 2 + gy ** 2) + 1e-6
bend = 55 * np.exp(-dist / 16)  # strongest right at the rim
yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
refracted = cv2.remap(blurred, xx - gx / norm * bend, yy - gy / norm * bend, cv2.INTER_LINEAR)

frost = refracted * 0.8 + 255 * 0.16
frost[..., 3] = 255
glass = frost * (A * 0.82)[..., None]

# 3. Light: bright rim where light hits the top-left edge, a softer pink rim bottom-right,
#    and a glossy highlight across the top of the glass.
Ab = cv2.GaussianBlur(A, (0, 0), 2.5)
ax = cv2.Sobel(Ab, cv2.CV_32F, 1, 0, ksize=3)
ay = cv2.Sobel(Ab, cv2.CV_32F, 0, 1, ksize=3)
mag = np.sqrt(ax ** 2 + ay ** 2)
lit = (ax * 0.6 + ay * 0.8) / (mag + 1e-6)
mag /= mag.max()
edge = np.clip(mag * np.clip(lit, 0, 1) * 1.6 + mag * 0.35, 0, 1)[..., None]
highlight = np.concatenate([np.repeat(255 * edge, 3, axis=2), 255 * edge], axis=2)
rim_tint = np.clip(mag * np.clip(-lit, 0, 1) * 0.9, 0, 1)[..., None]
tint = np.concatenate([np.array([255, 120, 255], np.float32) * rim_tint, 255 * rim_tint * 0.6], axis=2)

rows = np.where(inside.any(axis=1))[0]
top, height = rows.min(), rows.max() - rows.min()
sheen_curve = np.clip(1 - (yy - top) / (0.42 * height), 0, 1) ** 2
wave = np.clip(1 - np.abs((yy - top) - 0.18 * height - 0.08 * (xx - CX) ** 2 / S) / 40, 0, 1)
sheen_amount = (sheen_curve * 0.28 + wave * 0.18) * cv2.erode(A, np.ones((9, 9), np.uint8))
sheen = np.repeat(255 * sheen_amount[..., None], 4, axis=2)

# 4. Soft coloured shadow beneath the glass.
shadow_alpha = (cv2.GaussianBlur(np.roll(A, 24, axis=0), (0, 0), 22) * 0.55)[..., None]
shadow = np.concatenate([np.array([40, 8, 30], np.float32) * shadow_alpha, 255 * shadow_alpha], axis=2)


# 5. Eyeholes: dark glass with a glowing eye on the left, a lit keyhole on the right.
def draw_eyes(p):
    for eye in (left_eye, right_eye):
        p.fillPath(eye, QColor(10, 4, 30, 225))
    p.setClipPath(left_eye)
    iris = QRadialGradient(QPointF(*LEFT_EYE), 44)
    iris.setColorAt(0, QColor("#e6fffb"))
    iris.setColorAt(0.45, QColor("#2ef2d0"))
    iris.setColorAt(1, QColor("#1a5bff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(iris)
    p.drawEllipse(QPointF(*LEFT_EYE), 42, 42)
    p.setBrush(QColor("#050214"))
    p.drawEllipse(QPointF(*LEFT_EYE), 17, 17)
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawEllipse(QPointF(LEFT_EYE[0] + 14, LEFT_EYE[1] - 13), 8, 8)
    p.setClipping(False)
    light = QRadialGradient(QPointF(RIGHT_EYE[0], RIGHT_EYE[1] - 6), 60)
    light.setColorAt(0, QColor("#ffffff"))
    light.setColorAt(0.5, QColor("#fff0c0"))
    light.setColorAt(1, QColor("#ffb24a"))
    p.fillPath(keyhole(*RIGHT_EYE, 1.25), light)


def draw_glow(p):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2ef2d0"))
    p.drawEllipse(QPointF(*LEFT_EYE), 46, 46)
    p.fillPath(keyhole(*RIGHT_EYE, 1.4), QColor("#ffd27a"))


def draw_jewel(p):
    gem = QPainterPath()
    gem.moveTo(CX, 408)
    gem.lineTo(CX + 28, 446)
    gem.lineTo(CX, 484)
    gem.lineTo(CX - 28, 446)
    gem.closeSubpath()
    g = QRadialGradient(QPointF(CX - 8, 432), 50)
    g.setColorAt(0, QColor("#ffe3f6"))
    g.setColorAt(0.4, QColor("#ff4fc1"))
    g.setColorAt(1, QColor("#8a0f63"))
    p.fillPath(gem, g)
    p.setPen(QPen(QColor(255, 255, 255, 200), 4))
    p.drawPath(gem)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 230))
    p.drawEllipse(QPointF(CX - 7, 432), 7, 9)


eyes = render(draw_eyes, place=True)
glow_src = render(draw_glow, place=True)
glow = cv2.GaussianBlur(glow_src, (0, 0), 30) * 1.6 + cv2.GaussianBlur(glow_src, (0, 0), 9) * 0.7
jewel = render(draw_jewel, place=True)


# 6. Tile finish: sparkles, a glassy sheen on the tile's top half and a thin bright rim.
def draw_sparkles(p):
    sparkle(p, 818, 214, 30, 255)
    sparkle(p, 772, 180, 14, 210)
    sparkle(p, 196, 648, 18, 200)


def draw_tile_glass(p):
    p.setClipPath(tile)
    top_sheen = QRadialGradient(QPointF(CX, -200), 760)
    top_sheen.setColorAt(0.55, QColor(255, 255, 255, 60))
    top_sheen.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(0, 0, S, S), top_sheen)
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 70), 3))
    p.drawPath(tile)


sparkles = render(draw_sparkles)
finish = over(sparkles, cv2.GaussianBlur(sparkles, (0, 0), 8) * 0.6 * tile_alpha)
finish = over(finish, render(draw_tile_glass))

out = background
out = over(shadow * tile_alpha, out)
out = over(eyes, out)
out = over(glass, out)
out = over(tint, out)
out = out + highlight + sheen
out = over(jewel, out)
out = out + glow * tile_alpha
out = over(finish, out)
out = np.clip(out, 0, 255)
out[..., :3] = np.minimum(out[..., :3], out[..., 3:4])  # keep premultiplied colours valid
out = out.astype(np.uint8).copy()
QImage(out.data, S, S, 4 * S, QImage.Format.Format_ARGB32_Premultiplied).save(
    str(Path(__file__).with_name("AppIcon.png")))
