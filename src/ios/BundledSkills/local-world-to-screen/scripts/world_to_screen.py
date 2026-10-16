#!/usr/bin/env python3
"""World to Screen projection"""
import math, sys

def world_to_screen(pos, matrix, screen_w, screen_h):
    x = pos[0]*matrix[0] + pos[1]*matrix[1] + pos[2]*matrix[2] + matrix[3]
    y = pos[0]*matrix[4] + pos[1]*matrix[5] + pos[2]*matrix[6] + matrix[7]
    w = pos[0]*matrix[12] + pos[1]*matrix[13] + pos[2]*matrix[14] + matrix[15]
    if w < 0.001: return None
    return (screen_w/2*(1+x/w), screen_h/2*(1-y/w))

print("[world-to-screen] W2S module ready")
print("  Usage: world_to_screen(world_pos, view_matrix_16f, 1920, 1080)")
print("  Returns: (screen_x, screen_y) or None if behind camera")
