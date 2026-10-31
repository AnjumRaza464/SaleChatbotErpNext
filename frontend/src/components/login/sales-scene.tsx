"use client";

import { useEffect, useRef } from "react";

/**
 * Interactive 3D backdrop for the login page: an isometric "sales city" of
 * glowing bars (one per branch × month) on a perspective floor grid. Pure CSS
 * 3D; the pointer tilts the whole world and writes --mx/--my on the page root so
 * the floating chat bubbles (rendered by the page) drift with parallax. Honors
 * prefers-reduced-motion.
 */


// Deterministic bar heights (px) so the server and client render the same scene.
const HEIGHTS = [
  [46, 62, 54, 78, 70, 96, 88, 118],
  [38, 52, 66, 60, 84, 92, 104, 126],
  [30, 44, 50, 72, 68, 86, 110, 134],
  [24, 36, 58, 64, 90, 98, 120, 150],
];

const BARS = HEIGHTS.flatMap((row, y) =>
  row.map((h, x) => ({ x, y, h, hue: 205 + x * 9, delay: (x * 0.07 + y * 0.12).toFixed(2) })),
);

export function SalesScene() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stage = ref.current;
    if (!stage || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const el = stage.parentElement ?? stage; // the .lp-root, so bubbles outside the stage inherit the vars

    let raf = 0;
    let targetX = 0, targetZ = 0, curX = 0, curZ = 0;
    let targetMX = 0, targetMY = 0, curMX = 0, curMY = 0;

    const tick = () => {
      raf = 0;
      curX += (targetX - curX) * 0.08;
      curZ += (targetZ - curZ) * 0.08;
      curMX += (targetMX - curMX) * 0.08;
      curMY += (targetMY - curMY) * 0.08;
      el.style.setProperty("--tilt-x", `${curX.toFixed(2)}deg`);
      el.style.setProperty("--tilt-z", `${curZ.toFixed(2)}deg`);
      el.style.setProperty("--mx", curMX.toFixed(3));
      el.style.setProperty("--my", curMY.toFixed(3));
      if (Math.abs(targetX - curX) > 0.01 || Math.abs(targetZ - curZ) > 0.01 || Math.abs(targetMX - curMX) > 0.001) {
        raf = requestAnimationFrame(tick);
      }
    };

    const onMove = (e: PointerEvent) => {
      const nx = e.clientX / window.innerWidth - 0.5; // -0.5 .. 0.5
      const ny = e.clientY / window.innerHeight - 0.5;
      targetX = -ny * 12;
      targetZ = nx * 16;
      targetMX = nx;
      targetMY = ny;
      if (!raf) raf = requestAnimationFrame(tick);
    };
    const onLeave = () => {
      targetX = targetZ = targetMX = targetMY = 0;
      if (!raf) raf = requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div ref={ref} className="lp-stage" aria-hidden="true">
      <div className="lp-glow lp-glow-a" />
      <div className="lp-glow lp-glow-b" />

      <div className="lp-world">
        <div className="lp-floor" />
        <div className="lp-floor-light" />
        {BARS.map((b) => (
          <div
            key={`${b.x}-${b.y}`}
            className="lp-bar"
            style={
              {
                "--x": b.x,
                "--y": b.y,
                "--h": b.h,
                "--hue": b.hue,
                animationDelay: `${b.delay}s, ${b.delay}s`,
              } as React.CSSProperties
            }
          >
            <i className="lp-face lp-top" />
            <i className="lp-face lp-front" />
            <i className="lp-face lp-side" />
          </div>
        ))}
      </div>

    </div>
  );
}
