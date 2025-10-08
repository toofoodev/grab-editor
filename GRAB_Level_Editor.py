#!/usr/bin/env python3

import json
import math
import sys
import copy
from pathlib import Path
from dataclasses import dataclass, field
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QListWidget, QListWidgetItem, QSpinBox, QFormLayout, QDoubleSpinBox, QSplitter, QColorDialog, QToolBar, QFrame, QTabWidget, QComboBox)
from PySide6.QtGui import QColor, QAction, QImage, QCursor
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GLU import *
import os 

# --- Constants ---
SHAPES = {
    "cube": 1000,
    "sphere": 1001,
    "cylinder": 1002,
    "pyramid": 1003,
    "prism": 1004,
    "cone": 1005,
    "square pyramid": 1006
}

MATERIALS = {
    "default": 0,
    "grab": 1,
    "ice": 2,
    "lava": 3,
    "wood": 4,
    "grapple": 5,
    "lava grapple": 6,
    "breakable": 7,
    "colored": 8,
    "bounce": 9,
    "snow": 10
}

# All recognized node types
NODE_TYPES = {
    "levelNodeStatic", "levelNodeSign", "levelNodeStart", "levelNodeFinish", 
    "levelNodeGravity", "levelNodeParticleEmitter", "levelNodeTrigger", 
    "levelNodeSound"
}

# Reverse lookups for UI
SHAPE_NAMES = {v: k for k, v in SHAPES.items()}
MATERIAL_NAMES = {v: k for k, v in MATERIALS.items()}

DEFAULT_JSON = {
    "formatVersion": 12,
    "title": "New Level",
    "creators": ".index-editor",
    "description": ".index modding - grab-tools.live",
    "tags": [],
    "maxCheckpointCount": 10,
    "ambienceSettings": {
        "skyZenithColor": {"r": 0.28, "g": 0.476, "b": 0.73, "a": 1},
        "skyHorizonColor": {"r": 0.916, "g": 0.9574, "b": 0.9574, "a": 1},
        "sunAltitude": 45,
        "sunAzimuth": 315,
        "sunSize": 1,
        "fogDensity": 0
    },
    "levelNodes": []
}

@dataclass
class SceneNode:
    id: str = "node"
    type: str = "levelNodeStatic"
    
    # Common fields
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    sz: float = 1.0
    
    # Static Node fields
    shape: int = SHAPES["cube"] 
    material: int = MATERIALS["default"]
    color1: dict = field(default_factory=lambda: {'r': 1.0, 'g': 1.0, 'b': 1.0, 'a': 1.0}) # Nested color
    
    # Generic fields (for non-static nodes and general levelNode structure)
    color: dict = field(default_factory=lambda: {'r': 0.0, 'g': 0.0, 'b': 0.0, 'a': 1.0}) # Top-level color
    radius: float = 1.0 # For Start/Finish nodes
    text: str = "" # For Sign nodes
    mode: int = 0 # For Gravity nodes
    
    # Store all other arbitrary fields as a raw dict for round-tripping
    raw_data: dict = field(default_factory=dict)

    def to_json(self):
        # Start with the raw data to preserve unknown/complex fields
        nested = copy.deepcopy(self.raw_data) 

        # Update common fields
        nested["position"] = {"x": self.x, "y": self.y, "z": self.z}
        # Note: Rotation in original JSON is Quat (w,x,y,z), here we use a placeholder w=1.0 for Euler(rx,ry,rz)
        nested["rotation"] = {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0} 
        
        # Apply type-specific fields
        if self.type == "levelNodeStatic":
            nested["shape"] = self.shape
            nested["material"] = self.material
            nested["scale"] = {"x": self.sx, "y": self.sy, "z": self.sz}
            nested["color1"] = self.color1
        
        elif self.type == "levelNodeStart" or self.type == "levelNodeFinish":
            nested["radius"] = self.radius

        elif self.type == "levelNodeSign":
            nested["text"] = self.text

        # Scale is often used in other nodes like Gravity/Particle/Trigger
        if "scale" in nested:
             nested["scale"] = {"x": self.sx, "y": self.sy, "z": self.sz}
        
        # Build the final structure
        d = {self.type: nested}
        
        # Top-level color field
        if self.color:
            d["color"] = self.color
            
        return d

    @staticmethod
    def from_json(obj: dict):
        node_type = next(iter(obj))
        nested = obj.get(node_type, {}) or {}
        
        pos = nested.get("position", {}) or {}
        scl = nested.get("scale", {}) or {}
        
        # Initialize with all parsed nested fields (for raw_data)
        raw_data = copy.deepcopy(nested)
        
        # Extract common and specific fields
        shape = int(nested.get("shape", SHAPES["cube"]))
        material = int(nested.get("material", MATERIALS["default"]))
        radius = float(nested.get("radius", 1.0))
        text = str(nested.get("text", ""))
        mode = int(nested.get("mode", 0))

        color1 = nested.get("color1", {'r': 1.0, 'g': 1.0, 'b': 1.0, 'a': 1.0})
        color = obj.get("color", {'r': 0.0, 'g': 0.0, 'b': 0.0, 'a': 1.0})
        
        # Clean up raw_data to avoid duplication in the dataclass fields 
        raw_data.pop("position", None)
        raw_data.pop("scale", None)
        raw_data.pop("rotation", None)
        raw_data.pop("shape", None)
        raw_data.pop("material", None)
        raw_data.pop("color1", None)
        raw_data.pop("radius", None)
        raw_data.pop("text", None)
        raw_data.pop("mode", None)

        try:
            return SceneNode(
                id=str(nested.get("id", f"node_{node_type}")), 
                type=node_type,
                shape=shape,
                material=material,
                x=float(pos.get("x", 0.0)),
                y=float(pos.get("y", 0.0)),
                z=float(pos.get("z", 0.0)),
                rx=0.0, ry=0.0, rz=0.0, 
                sx=float(scl.get("x", 1.0)),
                sy=float(scl.get("y", 1.0)),
                sz=float(scl.get("z", 1.0)),
                color1=color1 if isinstance(color1, dict) else {'r': 1.0, 'g': 1.0, 'b': 1.0, 'a': 1.0},
                color=color if isinstance(color, dict) else {'r': 0.0, 'g': 0.0, 'b': 0.0, 'a': 1.0},
                radius=radius,
                text=text,
                mode=mode,
                raw_data=raw_data
            )
        except Exception as e:
            print(f"Error parsing node: {e}")
            return SceneNode()

class GLViewport(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus) 
        self.camera_distance = 20.0 
        self.camera_rot_x = 30.0 
        self.camera_rot_y = -45.0 
        self.pan_x = 0.0 
        self.pan_y = 0.0 
        self.pan_z = 0.0 
        
        self.last_pos = None
        self.nodes = []
        self.textures = {} 
        self.gl_texture_ids = {} 
        
        self.is_right_mouse_down = False
        self.key_states = {'W': False, 'A': False, 'S': False, 'D': False, 'E': False, 'Q': False}
        self.move_speed = 0.5 
        
        self.move_timer = QTimer(self)
        self.move_timer.timeout.connect(self._update_movement)
        self.move_timer.start(16)

    def initializeGL(self):
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [0, 10, 10, 0])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.3, 0.3, 0.3, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [0.7, 0.7, 0.7, 1.0])
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        
        glClearColor(0.5, 0.7, 0.9, 1.0)
        
        self._upload_textures()
        glEnable(GL_TEXTURE_2D) 

    def _upload_textures(self):
        if self.gl_texture_ids:
            glDeleteTextures(len(self.gl_texture_ids), list(self.gl_texture_ids.values()))
            self.gl_texture_ids = {}
            
        for mat_id, qimage in self.textures.items():
            texture_id = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, texture_id)

            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            
            image_data = qimage.convertToFormat(QImage.Format_RGB32) 
            ptr = image_data.bits()
            ptr.setsize(image_data.sizeInBytes())

            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA, image_data.width(), image_data.height(), 
                0, GL_RGBA, GL_UNSIGNED_BYTE, ptr.tobytes()
            )
            glGenerateMipmap(GL_TEXTURE_2D)
            
            self.gl_texture_ids[mat_id] = texture_id
            
        glBindTexture(GL_TEXTURE_2D, 0) 

    def resizeGL(self, w, h):
        if h <= 0: h = 1
        glViewport(0, 0, max(1, w), h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(60.0, float(max(1, w)) / float(h), 0.1, 1000.0) 
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        
        glRotatef(self.camera_rot_x, 1, 0, 0)
        glRotatef(self.camera_rot_y, 0, 1, 0)
        glTranslatef(-self.pan_x, -self.pan_y, -self.pan_z) 
        
        self._draw_grid()
        
        glEnable(GL_LIGHTING)
        for node in self.nodes:
            self._draw_node(node)
            
    def _update_movement(self):
        if not self.is_right_mouse_down or not any(self.key_states.values()):
            return

        dt = 0.016 
        speed = self.move_speed * dt * self.camera_distance

        ry_rad = math.radians(self.camera_rot_y)
        rx_rad = math.radians(self.camera_rot_x)
        
        # Forward Vector (W/S) - FULL 3D Look Direction
        forward_x = math.sin(ry_rad) * math.cos(rx_rad)
        forward_y = -math.sin(rx_rad)
        forward_z = -math.cos(ry_rad) * math.cos(rx_rad)
        
        # Strafe Vector (A/D) - XZ plane
        strafe_x = math.sin(ry_rad - math.pi / 2.0)
        strafe_z = -math.cos(ry_rad - math.pi / 2.0)

        moved = False
        
        if self.key_states['W']:
            self.pan_x += forward_x * speed
            self.pan_y += forward_y * speed
            self.pan_z += forward_z * speed
            moved = True
            
        if self.key_states['S']:
            self.pan_x -= forward_x * speed
            self.pan_y -= forward_y * speed
            self.pan_z -= forward_z * speed
            moved = True

        if self.key_states['A']:
            self.pan_x += strafe_x * speed
            self.pan_z += strafe_z * speed
            moved = True

        if self.key_states['D']:
            self.pan_x -= strafe_x * speed
            self.pan_z -= strafe_z * speed
            moved = True
            
        if self.key_states['E']:
            self.pan_y += speed
            moved = True
            
        if self.key_states['Q']:
            self.pan_y -= speed
            moved = True

        if moved:
            self.update()

    def mousePressEvent(self, event):
        self.last_pos = event.pos()
        if event.button() == Qt.RightButton:
            self.is_right_mouse_down = True
            self.setCursor(Qt.BlankCursor)
            self.grabMouse() 
            
        self.setFocus(Qt.MouseFocusReason)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.is_right_mouse_down = False
            self.unsetCursor()
            self.releaseMouse() 

    def mouseMoveEvent(self, event):
        if self.last_pos is None:
            self.last_pos = event.pos()
            return
            
        dx = event.x() - self.last_pos.x()
        dy = event.y() - self.last_pos.y()
        
        if self.is_right_mouse_down:
            self.camera_rot_y += dx * 0.15 
            self.camera_rot_x += dy * 0.15
            self.camera_rot_x = max(-89.9, min(89.9, self.camera_rot_x))
            
            center_x = self.width() // 2
            center_y = self.height() // 2
            
            QCursor.setPos(self.mapToGlobal(QPoint(center_x, center_y)))
            self.last_pos = QPoint(center_x, center_y) 

            self.update()
        
        elif event.buttons() & Qt.MidButton:
            factor = self.camera_distance * 0.002
            ry_rad = math.radians(self.camera_rot_y)
            self.pan_x -= (dx * math.cos(ry_rad) - dy * math.sin(ry_rad)) * factor
            self.pan_z -= (dx * math.sin(ry_rad) + dy * math.cos(ry_rad)) * factor
            self.update()
            self.last_pos = event.pos()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120.0
        self.camera_distance *= math.pow(0.9, delta)
        self.camera_distance = max(0.5, min(500.0, self.camera_distance))
        self.update()
        
    def keyPressEvent(self, event):
        key_map = {
            Qt.Key_W: 'W', Qt.Key_A: 'A', Qt.Key_S: 'S', Qt.Key_D: 'D', 
            Qt.Key_E: 'E', Qt.Key_Q: 'Q'
        }
        
        if event.key() in key_map:
            self.key_states[key_map[event.key()]] = True
            
        if event.key() == Qt.Key_Shift:
            self.move_speed = 1.5 
            
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key_map = {
            Qt.Key_W: 'W', Qt.Key_A: 'A', Qt.Key_S: 'S', Qt.Key_D: 'D', 
            Qt.Key_E: 'E', Qt.Key_Q: 'Q'
        }
        
        if event.key() in key_map:
            self.key_states[key_map[event.key()]] = False
            
        if event.key() == Qt.Key_Shift:
            self.move_speed = 0.5
            
        super().keyReleaseEvent(event)

    # --- Drawing Methods ---
    def _draw_grid(self, size=50, step=1):
        glDisable(GL_LIGHTING)
        glColor3f(0.6, 0.6, 0.6)
        glBegin(GL_LINES)
        for i in range(-size, size + 1, step):
            glVertex3f(i + self.pan_x % step, 0, -size + self.pan_z % step)
            glVertex3f(i + self.pan_x % step, 0, size + self.pan_z % step)
            glVertex3f(-size + self.pan_x % step, 0, i + self.pan_z % step)
            glVertex3f(size + self.pan_x % step, 0, i + self.pan_z % step)
        glEnd()
        glLineWidth(2.0)
        glBegin(GL_LINES)
        glColor3f(1.0, 0.0, 0.0)
        glVertex3f(0, 0.01, 0); glVertex3f(10, 0.01, 0)
        glColor3f(0.0, 1.0, 0.0)
        glVertex3f(0, 0.01, 0); glVertex3f(0, 10, 0)
        glColor3f(0.0, 0.0, 1.0)
        glVertex3f(0, 0.01, 0); glVertex3f(0, 0.01, 10)
        glEnd()
        glLineWidth(1.0)

    def _draw_cube(self, size=1.0):
        hs = size / 2.0
        glBegin(GL_QUADS)
        
        # Face 1: +X
        glNormal3f(1, 0, 0)
        glTexCoord2f(0.0, 0.0); glVertex3f(hs, -hs, -hs)
        glTexCoord2f(1.0, 0.0); glVertex3f(hs, -hs, hs)
        glTexCoord2f(1.0, 1.0); glVertex3f(hs, hs, hs)
        glTexCoord2f(0.0, 1.0); glVertex3f(hs, hs, -hs)

        # Face 2: -X
        glNormal3f(-1, 0, 0)
        glTexCoord2f(0.0, 0.0); glVertex3f(-hs, -hs, hs)
        glTexCoord2f(1.0, 0.0); glVertex3f(-hs, -hs, -hs)
        glTexCoord2f(1.0, 1.0); glVertex3f(-hs, hs, -hs)
        glTexCoord2f(0.0, 1.0); glVertex3f(-hs, hs, hs)

        # Face 3: +Y (Top)
        glNormal3f(0, 1, 0)
        glTexCoord2f(0.0, 0.0); glVertex3f(-hs, hs, -hs)
        glTexCoord2f(1.0, 0.0); glVertex3f(hs, hs, -hs)
        glTexCoord2f(1.0, 1.0); glVertex3f(hs, hs, hs)
        glTexCoord2f(0.0, 1.0); glVertex3f(-hs, hs, hs)

        # Face 4: -Y (Bottom)
        glNormal3f(0, -1, 0)
        glTexCoord2f(0.0, 0.0); glVertex3f(-hs, -hs, hs)
        glTexCoord2f(1.0, 0.0); glVertex3f(hs, -hs, hs)
        glTexCoord2f(1.0, 1.0); glVertex3f(hs, -hs, -hs)
        glTexCoord2f(0.0, 1.0); glVertex3f(-hs, -hs, -hs)

        # Face 5: +Z
        glNormal3f(0, 0, 1)
        glTexCoord2f(0.0, 0.0); glVertex3f(-hs, -hs, hs)
        glTexCoord2f(1.0, 0.0); glVertex3f(-hs, hs, hs)
        glTexCoord2f(1.0, 1.0); glVertex3f(hs, hs, hs)
        glTexCoord2f(0.0, 1.0); glVertex3f(hs, -hs, hs)

        # Face 6: -Z
        glNormal3f(0, 0, -1)
        glTexCoord2f(0.0, 0.0); glVertex3f(hs, -hs, -hs)
        glTexCoord2f(1.0, 0.0); glVertex3f(hs, hs, -hs)
        glTexCoord2f(1.0, 1.0); glVertex3f(-hs, hs, -hs)
        glTexCoord2f(0.0, 1.0); glVertex3f(-hs, -hs, -hs)
        glEnd()

    def _draw_sphere(self, radius, slices=16, stacks=16):
        quadratic = gluNewQuadric()
        gluQuadricNormals(quadratic, GLU_SMOOTH)
        gluSphere(quadratic, radius, slices, stacks)
        gluDeleteQuadric(quadratic)

    def _draw_node(self, node: SceneNode):
        glPushMatrix()
        
        glTranslatef(node.x, node.y, node.z)
        glRotatef(node.ry, 0, 1, 0) 
        glRotatef(node.rx, 1, 0, 0) 
        glRotatef(node.rz, 0, 0, 1) 
        glScalef(node.sx, node.sy, node.sz)
        
        # Determine color and drawing style based on node type
        if node.type == "levelNodeStatic":
            texture_id = self.gl_texture_ids.get(node.material)
            
            # --- START: Material Color Override ---
            if node.material == MATERIALS["grapple"]:
                # Green for Grapple (R=0, G=0.8, B=0)
                glColor3f(0.0, 0.8, 0.0)
            elif node.material == MATERIALS["wood"]:
                # Brown for Wood (R=0.5, G=0.3, B=0.1)
                glColor3f(0.5, 0.3, 0.1)
            else:
                # Default to node's color1
                c = node.color1
                cr, cg, cb = float(c.get('r', 1.0)), float(c.get('g', 1.0)), float(c.get('b', 1.0))
                glColor3f(cr, cg, cb)
            # --- END: Material Color Override ---
            
            if texture_id:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, texture_id)
                glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
            else:
                glDisable(GL_TEXTURE_2D)
            
            self._draw_cube(size=1.0) 
            
            if texture_id:
                glBindTexture(GL_TEXTURE_2D, 0)
                glDisable(GL_TEXTURE_2D)
                
        elif node.type in ["levelNodeStart", "levelNodeFinish"]:
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_LIGHTING)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            # Draw a transparent sphere scaled by radius (using x scale as proxy for radius)
            radius = node.radius * node.sx 
            if node.type == "levelNodeStart":
                glColor4f(0.0, 1.0, 0.0, 0.4) # Green Start
            else:
                glColor4f(1.0, 0.0, 0.0, 0.4) # Red Finish

            self._draw_sphere(radius=radius, slices=16, stacks=16)

            glDisable(GL_BLEND)
            glEnable(GL_LIGHTING)
            
        elif node.type in ["levelNodeSign", "levelNodeGravity", "levelNodeParticleEmitter", "levelNodeTrigger", "levelNodeSound"]:
            # Draw a simple wireframe cube or point for non-static objects
            glDisable(GL_TEXTURE_2D)
            glDisable(GL_LIGHTING)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            
            if node.type == "levelNodeSign":
                glColor3f(1.0, 1.0, 0.0) # Yellow
            elif node.type == "levelNodeGravity":
                glColor3f(0.0, 0.0, 1.0) # Blue
            elif node.type == "levelNodeParticleEmitter":
                glColor3f(1.0, 0.5, 0.0) # Orange
            elif node.type == "levelNodeTrigger":
                glColor3f(0.5, 0.0, 0.5) # Purple
            elif node.type == "levelNodeSound":
                glColor3f(0.5, 0.5, 0.5) # Grey

            self._draw_cube(size=1.0)
            
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            glEnable(GL_LIGHTING)

        glPopMatrix()

# --- MainWindow ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JSON 3D Scene Editor")
        self.resize(1200, 800)
        self.current_path = None
        self.scene_data = copy.deepcopy(DEFAULT_JSON)
        self.nodes = []
        self._editing_node = None 
        
        self.project_root = None
        if not self._setup_project_folder():
            QApplication.quit()
            return
        
        self.textures = self._load_textures()
        
        self._create_actions()
        self._create_toolbar()
        self._create_ui()
        
        self.viewport.textures = self.textures
        if self.viewport.context():
            self.viewport._upload_textures() 
            
        self._bind_actions()
        self.load_scene_from_data(self.scene_data)
        
        self.viewport.setFocus() 

    def _setup_project_folder(self):
        QMessageBox.information(self, "Select Project Folder", 
            "Please select or create the project folder where the level and its assets will be stored. Textures must be in the 'Assets/Textures' subfolder.")
            
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder", str(Path.home()))
        
        if not folder:
            return False
            
        self.project_root = Path(folder)
        
        texture_dir = self.project_root / "Assets" / "Textures"
        try:
            texture_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create Assets/Textures directory: {e}")
            return False
            
        return True

    def _load_textures(self):
        if not self.project_root:
            return {}
            
        texture_map = {}
        texture_base_path = self.project_root / "Assets" / "Textures"
        
        texture_files = {
            MATERIALS["default"]: "default_GRAB.png",
            MATERIALS["grab"]: "default_GRAB.png", 
            MATERIALS["lava"]: "lava_GRAB.jpg",
            MATERIALS["wood"]: "wood_GRAB.png",
            MATERIALS["grapple"]: "grapple_GRAB.jpg",
            MATERIALS["colored"]: "colored_GRAB.png", 
            MATERIALS["ice"]: "default_GRAB.png", 
            MATERIALS["lava grapple"]: "lava_GRAB.jpg", 
            MATERIALS["breakable"]: "default_GRAB.png", 
            MATERIALS["bounce"]: "colored_GRAB.png", 
            MATERIALS["snow"]: "colored_GRAB.png", 
        }

        for mat_id, filename in texture_files.items():
            path = texture_base_path / filename
            if path.exists():
                try:
                    qimage = QImage(str(path))
                    if not qimage.isNull():
                        texture_map[mat_id] = qimage 
                except Exception:
                    pass
        return texture_map

    def _create_actions(self):
        self.open_action = QAction("&Open...", self)
        self.save_action = QAction("&Save", self)
        self.save_as_action = QAction("Save &As...", self)
        self.new_action = QAction("&New", self)

    def _create_toolbar(self):
        tb = QToolBar("Main")
        self.addToolBar(tb)
        tb.addAction(self.new_action)
        tb.addAction(self.open_action)
        tb.addAction(self.save_action)
        tb.addAction(self.save_as_action)

    def _create_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        left = QWidget()
        left.setMinimumWidth(300) 
        left_layout = QVBoxLayout(left)
        splitter.addWidget(left)
        tabs = QTabWidget()
        left_layout.addWidget(tabs)
        
        # Info Tab
        info_tab = QWidget()
        info_layout = QFormLayout(info_tab)
        tabs.addTab(info_tab, "Level/Information")
        self.title_edit = QLineEdit()
        self.creators_edit = QLineEdit()
        self.desc_edit = QTextEdit()
        self.tags_edit = QLineEdit()
        self.max_checkpoints = QSpinBox(); self.max_checkpoints.setRange(0, 1000)
        info_layout.addRow("Title:", self.title_edit)
        info_layout.addRow("Creators:", self.creators_edit)
        info_layout.addRow("Description:", self.desc_edit)
        info_layout.addRow("Tags (comma):", self.tags_edit)
        info_layout.addRow("Max Checkpoints:", self.max_checkpoints)
        ambience_label = QLabel("Ambience (colors & sun)")
        info_layout.addRow(ambience_label)
        self.sky_zenith_btn = QPushButton("Sky Zenith Color")
        self.sky_horizon_btn = QPushButton("Sky Horizon Color")
        self.sun_altitude = QDoubleSpinBox(); self.sun_altitude.setRange(-90, 90)
        self.sun_azimuth = QDoubleSpinBox(); self.sun_azimuth.setRange(0, 360)
        self.sun_size = QDoubleSpinBox(); self.sun_size.setRange(0.001, 10.0)
        self.fog_density = QDoubleSpinBox(); self.fog_density.setRange(0.0, 100.0)
        info_layout.addRow(self.sky_zenith_btn, self.sky_horizon_btn)
        info_layout.addRow("Sun Altitude:", self.sun_altitude)
        info_layout.addRow("Sun Azimuth:", self.sun_azimuth)
        info_layout.addRow("Sun Size:", self.sun_size)
        info_layout.addRow("Fog Density:", self.fog_density)
        
        # Nodes Tab
        nodes_tab = QWidget()
        nodes_layout = QVBoxLayout(nodes_tab)
        tabs.addTab(nodes_tab, "Nodes")
        add_node_container = QHBoxLayout()
        self.add_node_combo = QComboBox()
        self.add_node_combo.addItems(sorted(list(NODE_TYPES)))
        self.add_level_node_btn = QPushButton("Add Selected Node Type")
        add_node_container.addWidget(self.add_node_combo)
        add_node_container.addWidget(self.add_level_node_btn)
        nodes_layout.addLayout(add_node_container)
        self.node_list = QListWidget()
        nodes_layout.addWidget(self.node_list)
        node_buttons = QHBoxLayout()
        nodes_layout.addLayout(node_buttons)
        self.add_node_btn = QPushButton("Duplicate Node")
        self.remove_node_btn = QPushButton("Remove Node")
        node_buttons.addWidget(self.add_node_btn)
        node_buttons.addWidget(self.remove_node_btn)
        
        # Right Panel (Viewport/Properties)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)
        self.viewport = GLViewport()
        self.viewport.setMinimumHeight(480)
        right_layout.addWidget(self.viewport)
        
        # Node Properties
        prop_frame = QFrame()
        prop_layout = QFormLayout(prop_frame)
        right_layout.addWidget(prop_frame)
        self.node_id = QLineEdit()
        self.node_type = QLineEdit() 
        self.node_shape = QComboBox(); self.node_shape.addItems(list(SHAPES.keys()))
        self.node_material = QComboBox(); self.node_material.addItems(list(MATERIALS.keys()))
        
        step = 0.1 
        self.pos_x = QDoubleSpinBox(); self.pos_x.setRange(-99999, 99999); self.pos_x.setSingleStep(step)
        self.pos_y = QDoubleSpinBox(); self.pos_y.setRange(-99999, 99999); self.pos_y.setSingleStep(step)
        self.pos_z = QDoubleSpinBox(); self.pos_z.setRange(-99999, 99999); self.pos_z.setSingleStep(step)
        self.rot_x = QDoubleSpinBox(); self.rot_x.setRange(-360, 360); self.rot_x.setSingleStep(1.0)
        self.rot_y = QDoubleSpinBox(); self.rot_y.setRange(-360, 360); self.rot_y.setSingleStep(1.0)
        self.rot_z = QDoubleSpinBox(); self.rot_z.setRange(-360, 360); self.rot_z.setSingleStep(1.0)
        self.scale_x = QDoubleSpinBox(); self.scale_x.setRange(0.001, 999); self.scale_x.setSingleStep(step)
        self.scale_y = QDoubleSpinBox(); self.scale_y.setRange(0.001, 999); self.scale_y.setSingleStep(step)
        self.scale_z = QDoubleSpinBox(); self.scale_z.setRange(0.001, 999); self.scale_z.setSingleStep(step)
        
        self.node_radius = QDoubleSpinBox(); self.node_radius.setRange(0.001, 999); self.node_radius.setSingleStep(step)
        self.node_text = QLineEdit()
        self.node_mode = QSpinBox(); self.node_mode.setRange(0, 100)
        
        self.color1_btn = QPushButton("Set Nested Color1 (Shader)")
        self.color_btn = QPushButton("Set Top Color (General)")
        
        prop_layout.addRow("ID:", self.node_id)
        prop_layout.addRow("Type:", self.node_type)
        
        # Static Node Fields
        prop_layout.addRow("Shape:", self.node_shape)
        prop_layout.addRow("Material:", self.node_material)
        
        # Transform
        prop_layout.addRow("Pos X:", self.pos_x)
        prop_layout.addRow("Pos Y:", self.pos_y)
        prop_layout.addRow("Pos Z:", self.pos_z)
        prop_layout.addRow("Rot X:", self.rot_x)
        prop_layout.addRow("Rot Y:", self.rot_y)
        prop_layout.addRow("Rot Z:", self.rot_z)
        prop_layout.addRow("Scale X:", self.scale_x)
        prop_layout.addRow("Scale Y:", self.scale_y)
        prop_layout.addRow("Scale Z:", self.scale_z)
        
        # Specific Fields
        prop_layout.addRow("Radius:", self.node_radius)
        prop_layout.addRow("Text:", self.node_text)
        prop_layout.addRow("Mode:", self.node_mode)

        # Color Fields
        prop_layout.addRow(self.color1_btn) 
        prop_layout.addRow(self.color_btn)
        
        apply_row = QHBoxLayout()
        self.apply_node_btn = QPushButton("Apply")
        apply_row.addWidget(self.apply_node_btn)
        right_layout.addLayout(apply_row)
        
        splitter.setSizes([300, 900])
        
        # Initial state of property fields
        self._set_property_fields_enabled(False)


    def on_new(self):
        reply = QMessageBox.question(self, 'New Level', 
            "Are you sure you want to start a new level? Unsaved changes will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.current_path = None
            self.scene_data = copy.deepcopy(DEFAULT_JSON)
            self.load_scene_from_data(self.scene_data)
            self.setWindowTitle("JSON 3D Scene Editor")
            self.viewport.setFocus()

    def _bind_actions(self):
        self.open_action.triggered.connect(self.on_open)
        self.save_action.triggered.connect(self.on_save)
        self.save_as_action.triggered.connect(self.on_save_as)
        self.new_action.triggered.connect(self.on_new)
        
        self.add_level_node_btn.clicked.connect(self.on_add_level_node)
        self.add_node_btn.clicked.connect(self.on_duplicate_node)
        self.remove_node_btn.clicked.connect(self.on_remove_node)
        self.node_list.currentItemChanged.connect(self.on_node_selected)
        self.apply_node_btn.clicked.connect(self.on_apply_node)
        
        self.sky_zenith_btn.clicked.connect(lambda: self.on_pick_ambience_color('skyZenithColor'))
        self.sky_horizon_btn.clicked.connect(lambda: self.on_pick_ambience_color('skyHorizonColor'))
        
        self.color1_btn.clicked.connect(lambda: self.on_pick_node_color('color1'))
        self.color_btn.clicked.connect(lambda: self.on_pick_node_color('color'))
        
        self.sun_altitude.valueChanged.connect(self._update_ambience_from_ui)
        self.sun_azimuth.valueChanged.connect(self._update_ambience_from_ui)
        self.sun_size.valueChanged.connect(self._update_ambience_from_ui)
        self.fog_density.valueChanged.connect(self._update_ambience_from_ui)
        
        self.title_edit.editingFinished.connect(self._commit_ui_to_data)
        self.creators_edit.editingFinished.connect(self._commit_ui_to_data)
        self.desc_edit.textChanged.connect(self._commit_ui_to_data)
        self.tags_edit.editingFinished.connect(self._commit_ui_to_data)
        self.max_checkpoints.valueChanged.connect(self._commit_ui_to_data)


    def on_add_level_node(self):
        selected_type = self.add_node_combo.currentText()
        node = SceneNode(
            id=f"{selected_type}_{len(self.nodes)}",
            type=selected_type,
            shape=SHAPES["cube"],
            material=MATERIALS["default"]
        )
        self.nodes.append(node)
        item = QListWidgetItem(f"{node.id} ({node.type})")
        item.setData(Qt.UserRole, node)
        self.node_list.addItem(item)
        self.node_list.setCurrentItem(item)
        self.viewport.update()

    def on_duplicate_node(self):
        current_item = self.node_list.currentItem()
        if not current_item:
            self.on_add_level_node()
            return
            
        original_node = current_item.data(Qt.UserRole)
        node = copy.deepcopy(original_node)
        node.id = f"{node.type}_{len(self.nodes)}" 
        node.x += 1.0
        node.y += 1.0
        
        self.nodes.append(node)
        item = QListWidgetItem(f"{node.id} ({node.type})")
        item.setData(Qt.UserRole, node)
        self.node_list.addItem(item)
        self.node_list.setCurrentItem(item)
        self.viewport.update()

    def on_open(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open Scene JSON", str(self.project_root), "JSON Files (*.json);;All Files (*)")
        if not p:
            return
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.current_path = Path(p)
            self.scene_data = data
            self.load_scene_from_data(data)
            self.viewport.setFocus()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")

    def on_save(self):
        self._commit_ui_to_data() 
        if self.current_path:
            try:
                with open(self.current_path, 'w', encoding='utf-8') as f:
                    json.dump(self.scene_data, f, indent=4)
                QMessageBox.information(self, "Saved", f"Saved to {self.current_path.name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file:\n{e}")
        else:
            self.on_save_as()

    def on_save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save Scene As", str(self.project_root / "scene.json"), "JSON Files (*.json);;All Files (*)")
        if not p:
            return
        self.current_path = Path(p)
        self.on_save()

    def on_remove_node(self):
        it = self.node_list.currentItem()
        if not it:
            return
        idx = self.node_list.row(it)
        if idx >= 0 and idx < len(self.nodes):
            if self.nodes[idx] is self._editing_node:
                self._editing_node = None 
            del self.nodes[idx]
            self.node_list.takeItem(idx)
            self.viewport.update()

    def on_node_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        if not current:
            self._editing_node = None
            self._set_property_fields_enabled(False)
            return
        node = current.data(Qt.UserRole)
        self._display_node(node)
        self.viewport.setFocus()
        
    def _set_property_fields_enabled(self, enabled):
        """Enables/disables property widgets based on selection."""
        self.apply_node_btn.setEnabled(enabled)
        self.node_id.setEnabled(enabled)
        self.pos_x.setEnabled(enabled)
        self.pos_y.setEnabled(enabled)
        self.pos_z.setEnabled(enabled)
        self.rot_x.setEnabled(enabled)
        self.rot_y.setEnabled(enabled)
        self.rot_z.setEnabled(enabled)
        self.scale_x.setEnabled(enabled)
        self.scale_y.setEnabled(enabled)
        self.scale_z.setEnabled(enabled)
        self.node_radius.setEnabled(enabled)
        self.node_text.setEnabled(enabled)
        self.node_mode.setEnabled(enabled)
        self.color_btn.setEnabled(enabled)
        self.color1_btn.setEnabled(enabled)

        # Type-specific enablement (always allow reading the type)
        self.node_type.setEnabled(False) # Should not be editable directly

    def _display_node(self, node: SceneNode):
        self._editing_node = node
        self._set_property_fields_enabled(True)
        
        self.node_id.setText(node.id)
        self.node_type.setText(node.type)
        
        # Set Static Node fields
        is_static = node.type == "levelNodeStatic"
        shape_name = SHAPE_NAMES.get(node.shape, "cube")
        material_name = MATERIAL_NAMES.get(node.material, "default")
        self.node_shape.setCurrentText(shape_name)
        self.node_material.setCurrentText(material_name)
        self.node_shape.setEnabled(is_static)
        self.node_material.setEnabled(is_static)
        self.color1_btn.setEnabled(is_static)
        
        # Set Transform
        self.pos_x.setValue(node.x)
        self.pos_y.setValue(node.y)
        self.pos_z.setValue(node.z)
        self.rot_x.setValue(node.rx)
        self.rot_y.setValue(node.ry)
        self.rot_z.setValue(node.rz)
        self.scale_x.setValue(node.sx)
        self.scale_y.setValue(node.sy)
        self.scale_z.setValue(node.sz)
        
        # Set Specific fields
        self.node_radius.setValue(node.radius)
        self.node_text.setText(node.text)
        self.node_mode.setValue(node.mode)
        
        self.node_radius.setEnabled(node.type in ["levelNodeStart", "levelNodeFinish"])
        self.node_text.setEnabled(node.type == "levelNodeSign")
        self.node_mode.setEnabled(node.type == "levelNodeGravity")

    def on_apply_node(self):
        node = self._editing_node
        if not node:
            return
            
        node.id = self.node_id.text()
        
        # Transform
        node.x = self.pos_x.value()
        node.y = self.pos_y.value()
        node.z = self.pos_z.value()
        node.rx = self.rot_x.value()
        node.ry = self.rot_y.value()
        node.rz = self.rot_z.value()
        node.sx = self.scale_x.value()
        node.sy = self.scale_y.value()
        node.sz = self.scale_z.value()
        
        # Static Node fields
        if node.type == "levelNodeStatic":
            node.shape = SHAPES.get(self.node_shape.currentText(), SHAPES["cube"])
            node.material = MATERIALS.get(self.node_material.currentText(), MATERIALS["default"])
        
        # Specific fields
        if node.type in ["levelNodeStart", "levelNodeFinish"]:
            node.radius = self.node_radius.value()
        
        if node.type == "levelNodeSign":
            node.text = self.node_text.text()

        if node.type == "levelNodeGravity":
            node.mode = self.node_mode.value()
            
        for i in range(self.node_list.count()):
            it = self.node_list.item(i)
            if it.data(Qt.UserRole) is node:
                it.setText(f"{node.id} ({node.type})")
                break
        self.viewport.update()
        
    def _commit_ui_to_data(self):
        self.scene_data['title'] = self.title_edit.text()
        self.scene_data['creators'] = self.creators_edit.text()
        self.scene_data['description'] = self.desc_edit.toPlainText()
        tags = [t.strip() for t in self.tags_edit.text().split(',') if t.strip()]
        self.scene_data['tags'] = tags
        self.scene_data['maxCheckpointCount'] = int(self.max_checkpoints.value())
        
        self._update_ambience_from_ui() 

        self.scene_data['levelNodes'] = [n.to_json() for n in self.nodes]

    def load_scene_from_data(self, data: dict):
        if data is None:
            data = copy.deepcopy(DEFAULT_JSON)
            
        self.scene_data = data
        
        self.title_edit.setText(str(data.get('title', '')))
        self.creators_edit.setText(str(data.get('creators', '')))
        self.desc_edit.setPlainText(str(data.get('description', '')))
        tags = data.get('tags', [])
        self.tags_edit.setText(', '.join(map(str, tags))) 
        
        try:
            self.max_checkpoints.setValue(int(data.get('maxCheckpointCount', 0)))
        except Exception:
            self.max_checkpoints.setValue(0)
            
        amb = data.get('ambienceSettings', {})
        self.sun_altitude.setValue(float(amb.get('sunAltitude', 45)))
        self.sun_azimuth.setValue(float(amb.get('sunAzimuth', 315)))
        self.sun_size.setValue(float(amb.get('sunSize', 1)))
        self.fog_density.setValue(float(amb.get('fogDensity', 0)))
        
        self.nodes = []
        self.node_list.clear()
        for obj in data.get('levelNodes', []):
            n = SceneNode.from_json(obj)
            self.nodes.append(n)
            item = QListWidgetItem(f"{n.id} ({n.type})")
            item.setData(Qt.UserRole, n)
            self.node_list.addItem(item)
            
        self.viewport.nodes = self.nodes
        self.viewport.update()
        
        self._editing_node = None 
        self._set_property_fields_enabled(False)
        if self.node_list.count() > 0:
            self.node_list.setCurrentRow(0)
            
    def on_pick_ambience_color(self, key: str):
        ambience = self.scene_data.get('ambienceSettings', {})
        existing = ambience.get(key, {})
        r = int(existing.get('r', 1.0) * 255)
        g = int(existing.get('g', 1.0) * 255)
        b = int(existing.get('b', 1.0) * 255)
        a = int(existing.get('a', 1.0) * 255)
        col = QColor(r, g, b, a)
        
        c = QColorDialog.getColor(col, self, f"Pick {key} Color")
        if not c.isValid():
            return
            
        r, g, b, a = c.redF(), c.greenF(), c.blueF(), c.alphaF()
        
        if 'ambienceSettings' not in self.scene_data:
            self.scene_data['ambienceSettings'] = {}
        self.scene_data['ambienceSettings'][key] = {'r': r, 'g': g, 'b': b, 'a': a}
        self.viewport.update()

    def on_pick_node_color(self, color_field: str):
        node = self._editing_node
        if not node:
            return
        
        existing = getattr(node, color_field) or {'r': 1.0, 'g': 1.0, 'b': 1.0, 'a': 1.0}
        
        r = int(existing.get('r', 1.0) * 255)
        g = int(existing.get('g', 1.0) * 255)
        b = int(existing.get('b', 1.0) * 255)
        col = QColor(r, g, b)
        
        c = QColorDialog.getColor(col, self, f"Pick Node {color_field} Color")
        if not c.isValid():
            return
            
        # Update the color field on the SceneNode object
        setattr(node, color_field, {'r': c.redF(), 'g': c.greenF(), 'b': c.blueF(), 'a': c.alphaF()})
        self.viewport.update()

    def _update_ambience_from_ui(self):
        amb = self.scene_data.get('ambienceSettings', {})
        amb['sunAltitude'] = self.sun_altitude.value()
        amb['sunAzimuth'] = self.sun_azimuth.value()
        amb['sunSize'] = self.sun_size.value()
        amb['fogDensity'] = self.fog_density.value()
        self.scene_data['ambienceSettings'] = amb
        self.viewport.update()

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    if win.project_root: 
        win.show()
        sys.exit(app.exec()) 
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()