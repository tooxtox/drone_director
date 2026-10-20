/** Backend bearings are clockwise from north; this model's nose points along +X. */
export function headingToYaw(heading: number): number {
  return (90 - heading) * Math.PI / 180;
}

/** Turn by the shortest arc, with a finite yaw rate (including the 359°/0° seam). */
export function turnToward(current: number, target: number, dt: number): number {
  const difference = Math.atan2(Math.sin(target - current), Math.cos(target - current));
  const limit = Math.PI * .75 * Math.max(0, dt);
  return current + Math.max(-limit, Math.min(limit, difference));
}
