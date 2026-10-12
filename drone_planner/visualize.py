"""Визуализация маршрутов через matplotlib."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


COLORS = [
    "#e6194B", "#3cb44b", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45",
    "#fabed4", "#469990",
]


def plot_all(zones, bases, paths, output_png="paths.png"):
    fig, ax = plt.subplots(figsize=(16, 14))

    # ── Зоны ──
    for zone in zones:
        if hasattr(zone, "polygon") and zone.polygon is not None:
            coords = list(zone.polygon.exterior.coords)
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.fill(xs, ys, alpha=0.08, color="gray",
                    edgecolor="black", linewidth=1, zorder=1)
            c = zone.polygon.centroid
            ax.annotate(f"{zone.name}\n{zone.area:.2f} км²",
                        (c.x, c.y), fontsize=10, ha="center",
                        color="dimgray", zorder=2)

    # ── Базы ──
    for b in bases:
        ax.plot(b.lon, b.lat, marker="*", color="black",
                markersize=20, zorder=25)
        ax.annotate(b.name, (b.lon, b.lat), fontsize=11,
                    color="black", xytext=(8, 8),
                    textcoords="offset points", zorder=26)

    # ── Галсы ──
    unit_colors = {}
    color_idx = 0

    for path in paths:
        if path.unit_name not in unit_colors:
            unit_colors[path.unit_name] = COLORS[color_idx % len(COLORS)]
            color_idx += 1
        color = unit_colors[path.unit_name]

        # Галсы с номерами и направлениями
        for i, line in enumerate(path.lines):
            xs = [line.start[0], line.end[0]]
            ys = [line.start[1], line.end[1]]
            ax.plot(xs, ys, color=color, linewidth=2,
                    label=path.unit_name if i == 0 else None,
                    zorder=10)

            # Номер + направление в середине галса
            mid_lon = (line.start[0] + line.end[0]) / 2
            mid_lat = (line.start[1] + line.end[1]) / 2
            label = f"{line.index}{line.direction}"
            ax.annotate(label, (mid_lon, mid_lat),
                        fontsize=8, color=color, ha="center",
                        bbox=dict(boxstyle="round,pad=0.15",
                                  facecolor="white", edgecolor=color,
                                  alpha=0.8),
                        zorder=12)

            # Стрелка в направлении галса
            ax.annotate("",
                        xy=(line.end[0], line.end[1]),
                        xytext=(line.start[0], line.start[1]),
                        arrowprops=dict(arrowstyle="->",
                                        color=color, lw=1.5,
                                        alpha=0.6),
                        zorder=9)

        # Перегоны (пунктирные линии между галсами)
        for seg in path.transfer_segments:
            pts = list(seg)
            ax.plot([p[0] for p in pts], [p[1] for p in pts],
                    color=color, linestyle=":",
                    linewidth=1.0, alpha=0.5, zorder=5)

        # START / END
        if path.entry_point:
            lon, lat = path.entry_point
            ax.plot(lon, lat, marker="o", color="lime",
                    markersize=14, markeredgecolor="black",
                    markeredgewidth=2, zorder=20)
            ax.annotate("START", (lon, lat), fontsize=9,
                        color="black", xytext=(6, 6),
                        textcoords="offset points", zorder=21)

        if path.exit_point:
            lon, lat = path.exit_point
            ax.plot(lon, lat, marker="X", color="red",
                    markersize=14, markeredgecolor="black",
                    markeredgewidth=2, zorder=20)
            ax.annotate("END", (lon, lat), fontsize=9,
                        color="black", xytext=(6, 6),
                        textcoords="offset points", zorder=21)

        # Перелёты база → START, END → база
        base = next((b for b in bases if b.name == path.base_name), None)
        if base and path.entry_point and path.exit_point:
            out = path.transit_out or [
                (base.lon, base.lat),
                (path.entry_point[0], path.entry_point[1]),
            ]
            back = path.transit_back or [
                (path.exit_point[0], path.exit_point[1]),
                (base.lon, base.lat),
            ]
            ax.plot([p[0] for p in out], [p[1] for p in out],
                    color=color, linestyle="--",
                    linewidth=1.0, alpha=0.7, zorder=6)
            ax.plot([p[0] for p in back], [p[1] for p in back],
                    color=color, linestyle="--",
                    linewidth=1.0, alpha=0.7, zorder=6)

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Маршруты дронов по зонам (с направлениями и перегонами)")
    ax.grid(True, alpha=0.3)
    ax.set_aspect("equal")

    legend = ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
        fontsize=8,
        frameon=True,
    )
    fig.savefig(output_png, dpi=150, bbox_inches="tight",
                bbox_extra_artists=[legend])
    plt.close()
    print(f"Визуализация: {output_png}")