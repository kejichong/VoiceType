"""用几何和亮度指标客观检查悬浮球的绘制，不靠肉眼。

起因是旧版有两个画法上的硬伤，肉眼一眼能看出但断言测不出：
1. 录音光晕画在 (-3,-3,s+6,s+6) 上，画布只有球那么大，光晕被整个裁掉 = 等于没画
2. 麦克风图标全用 int() 取整坐标，48px 上误差累积让图标明显歪

这两条现在都能测：光晕看"球外一圈有没有着色像素"，图标歪不歪看白色像素质心。

抓帧拿到的是**物理像素**（本机 150% 缩放，68 -> 102），所以所有几何判断都按
占画布的比例算，不能写死像素值。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ui.floatbtn import FloatingButton  # noqa: E402

CANVAS = 68          # 与 _SIZE 一致
BALL_R = 24          # 与 _BALL_R 一致
F_BALL = BALL_R / float(CANVAS)      # 球半径占画布的比例 0.353
F_HALO = (BALL_R + 2) / float(CANVAS)
F_MAX = 32.0 / CANVAS


def grab(state: str, hover: bool = False) -> QImage:
    """画一帧到透明画布上，保留 alpha。

    不能用 QWidget.grab() 或 render()：两者都会先把 widget 背景铺成不透明的
    Qt 默认灰(227,227,227)，透明通道全丢 —— 于是"球外一圈有没有光晕"这种判断
    会恒成立（整张图都不透明），测试等于没测。render() 传 DrawChildren 也没用，
    因为这是顶层窗口（Qt.Tool）的固有行为。
    所以 FloatingButton 把绘制主体抽成了 _paint_to(painter, size)，
    测试直接对一张透明 QImage 作画。
    """
    btn = FloatingButton()
    btn._state = state
    btn._hover = hover
    img = QImage(btn.width(), btn.height(), QImage.Format_ARGB32)
    # 用明确的 QColor，别用 Qt.transparent —— 后者在重载解析下不一定得到全透明
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    btn._paint_to(p, btn.width())
    p.end()
    btn.close()
    return img


def alpha_ok(img: QImage) -> bool:
    """grab() 有没有保留透明通道。角落必须是全透明，否则说明背景被填成不透明了，
    那些依赖 alpha 的判断就不能信。"""
    return img.pixelColor(2, 2).alpha() == 0


def profile(img: QImage) -> dict[float, tuple[int, float, float]]:
    """按到球心的距离（归一化）分桶：{r比例: (像素数, 平均alpha, 平均亮度)}。"""
    c = img.width() / 2.0
    w = float(img.width())
    buckets: dict[float, list[tuple[int, int]]] = {}
    for y in range(img.height()):
        for x in range(img.width()):
            col = img.pixelColor(x, y)
            if col.alpha() <= 6:
                continue
            r = math.hypot(x + 0.5 - c, y + 0.5 - c) / w
            lum = (col.red() * 299 + col.green() * 587 + col.blue() * 114) // 1000
            # 粒度 0.001 太细：半径 24 的圆周上，落进 0.001 宽度环里的只有 ~10 个像素，
            # 后面"这一环像素数 > 20"的判据会永远不成立。0.01 约合 0.68px，够用了。
            buckets.setdefault(round(r, 2), []).append((col.alpha(), lum))
    return {
        r: (
            len(v),
            sum(a for a, _ in v) / len(v),
            sum(l for _, l in v) / len(v),
        )
        for r, v in buckets.items()
    }


def ink_centroid(img: QImage) -> tuple[float, float, int]:
    """白色图标像素的质心（归一化到 0~1）与数量。图标歪不歪看这个。"""
    w = float(img.width())
    sx = sy = 0.0
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            col = img.pixelColor(x, y)
            # 图标是白色墨叠在半透明深色球上，SourceOver 之后实测约 (191,192,195)
            # 而不是纯白 —— 阈值写 200 会把图标整个判成"不存在"。球体本身约 (46,51,59)，
            # 取 140 正好把两者分开。
            if col.alpha() > 150 and col.red() > 140 and col.green() > 140 \
                    and col.blue() > 140:
                sx += (x + 0.5) / w
                sy += (y + 0.5) / w
                n += 1
    if not n:
        return (0.5, 0.5, 0)
    return (sx / n, sy / n, n)


def pixel_at(img: QImage, fx: float, fy: float) -> QColor:
    return img.pixelColor(int(img.width() * fx), int(img.height() * fy))


def main() -> int:
    QApplication(sys.argv)
    ok_all = True

    def check(ok: bool, label: str, detail: str = "") -> None:
        nonlocal ok_all
        ok_all &= ok
        print(("PASS " if ok else "FAIL ") + label + (f"  {detail}" if detail else ""))

    idle_img, rec_img = grab("idle"), grab("recording")
    w = idle_img.width()
    print(f"抓帧尺寸 {w}x{idle_img.height()}"
          f"（设计画布 {CANVAS}，本机缩放 {w / CANVAS:.2f}x）")
    corner = idle_img.pixelColor(1, 1)
    midc = idle_img.pixelColor(idle_img.width() // 2, 12)
    has_alpha = alpha_ok(idle_img)
    print(f"透明通道：角落 rgba({corner.red()},{corner.green()},"
          f"{corner.blue()},{corner.alpha()}) -> {'保留' if has_alpha else '不透明'}")
    print(f"球顶部像素 rgba({midc.red()},{midc.green()},{midc.blue()},{midc.alpha()})\n")

    p_idle, p_rec = profile(idle_img), profile(rec_img)

    # ---- 1. 光晕：旧版被画布裁掉，这项必失败 ----
    ring_idle = sum(v[0] for r, v in p_idle.items() if F_HALO <= r <= F_MAX)
    ring_rec = sum(v[0] for r, v in p_rec.items() if F_HALO <= r <= F_MAX)
    check(
        ring_rec > ring_idle * 1.5 and ring_rec > 800,
        "录音时的呼吸光晕画出来了（在球的外面）",
        f"球外着色像素 空闲={ring_idle} 录音={ring_rec}",
    )

    # ---- 2. 光晕不能溢出画布，否则边缘会被切出一条硬边 ----
    max_r = max(p_rec.keys())
    check(
        max_r <= 0.5,
        "光晕没有溢出画布（不会在边缘被切出硬边）",
        f"最外半径={max_r:.3f}（半幅=0.500）",
    )

    # ---- 3. 球体占满设计半径，外面留出透明画布给阴影和光晕 ----
    solid = [r for r, v in p_idle.items() if v[0] > 20 and v[1] > 90]
    r_ball = max(solid)
    check(
        abs(r_ball - F_BALL) < 0.02,
        "球的可见半径符合设计值",
        f"实测={r_ball:.3f}，设计={F_BALL:.3f}",
    )
    check(
        r_ball < 0.5 - 0.06,
        "球外围留出了透明画布（阴影和光晕有地方画）",
        f"球半径={r_ball:.3f}，半幅=0.500",
    )

    # ---- 4. 图标居中：旧版 int() 取整会歪 ----
    cx, cy, n_ink = ink_centroid(idle_img)
    check(n_ink > 120, "图标有足够的像素（不是空的）", f"{n_ink} 个白色像素")
    check(
        abs(cx - 0.5) < 0.012 and abs(cy - 0.5) < 0.015,
        "麦克风图标居中（没有因取整而歪）",
        f"质心 ({cx:.3f}, {cy:.3f})，球心 (0.500, 0.500)",
    )

    # ---- 5. 球体有明暗渐变，不是一坨纯色 ----
    top = pixel_at(idle_img, 0.5, 0.5 - F_BALL * 0.62)
    bot = pixel_at(idle_img, 0.5, 0.5 + F_BALL * 0.62)
    lt = top.red() * 299 + top.green() * 587 + top.blue() * 114
    lb = bot.red() * 299 + bot.green() * 587 + bot.blue() * 114
    check(
        lt > lb * 1.2,
        "球有上下明暗渐变（不是扁平纯色）",
        f"上半亮度={lt // 1000}，下半亮度={lb // 1000}",
    )

    # ---- 6. 空闲态半透明，不挡视线（依赖透明通道）----
    if has_alpha:
        key = min(p_idle.keys(), key=lambda r: abs(r - (r_ball - 0.012)))
        a_ball = p_idle[key][1]
        check(
            a_ball < 220,
            "空闲态是半透明的（不挡视线）",
            f"球边缘平均 alpha={a_ball:.0f}",
        )
    else:
        print("SKIP 空闲态半透明 —— grab 没保留透明通道，改由人工比对截图确认")

    # ---- 7. 各状态颜色确实不同 ----
    def mid(state: str) -> tuple[int, int, int]:
        # 取球体左侧：正上方和正下方都落在麦克风图标上，取不到球本身的颜色
        col = pixel_at(grab(state), 0.28, 0.5)
        return (col.red(), col.green(), col.blue())

    m_idle, m_rec, m_done = mid("idle"), mid("recording"), mid("done")
    check(m_rec[0] > m_idle[0] + 40, "录音态是红色，与空闲明显区分",
          f"{m_idle} -> {m_rec}")
    check(m_done[1] > m_done[0] + 25, "完成态是绿色", f"{m_done}")
    check(m_idle[0] < 90 and abs(m_idle[0] - m_idle[2]) < 30,
          "空闲态是低调的深色球", f"{m_idle}")

    print("\n" + ("全部通过" if ok_all else "存在失败项"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
