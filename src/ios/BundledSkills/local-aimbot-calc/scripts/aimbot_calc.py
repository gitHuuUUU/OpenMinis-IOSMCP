#!/usr/bin/env python3
"""Aimbot angle calculator"""
import math, sys

def calc_angle(local, target):
    dx, dy, dz = target[0]-local[0], target[1]-local[1], target[2]-local[2]
    hyp = math.sqrt(dx**2 + dy**2)
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = -math.degrees(math.atan2(dz, hyp))
    return (pitch % 360, yaw % 360)

def smooth_aim(current, target, factor=5.0):
    delta_p = target[0] - current[0]
    delta_y = target[1] - current[1]
    if delta_y > 180: delta_y -= 360
    if delta_y < -180: delta_y += 360
    return (current[0]+delta_p/factor, current[1]+delta_y/factor)

def fov_check(angles, target_pos, max_fov=90):
    local = (0,0,0)  # placeholder
    aim = calc_angle(local, target_pos)
    dist = math.sqrt((aim[0]-angles[0])**2 + (aim[1]-angles[1])**2)
    return dist <= max_fov

print("[aimbot-calc] Aimbot math module ready")
print("  calc_angle(local_xyz, target_xyz) -> (pitch, yaw)")
print("  smooth_aim(current_angles, target_angles, factor=5.0) -> (pitch, yaw)")
print("  fov_check(view_angles, target_pos, max_fov=90) -> bool")
