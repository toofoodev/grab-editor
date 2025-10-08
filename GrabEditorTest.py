#!/usr/bin/env python3
# -*- coding: utf-8 -*- 

import json
import math
import sys
import copy
from pathlib import Path
from dataclasses import dataclass, field
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QListWidget, QListWidgetItem, QSpinBox, QFormLayout, QDoubleSpinBox, QSplitter, QColorDialog, QToolBar, QFrame, QTabWidget, QComboBox)
from PySide6.QtGui import QColor, QAction, QImage, QCursor
from PySide6.QtCore import Qt, QPoint, QTimer, Signal 
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

# --- UPDATED MATERIALS DICTIONARY ---
# This dictionary now matches the LevelNodeMaterial enum in the latest types.proto:
# DEFAULT(0), GRABBABLE(1), GRABBABLE_CRUMBLING(2), DEATH(3), WOOD(4), COLORED_GRABBABLE(5), GRAPPLE_HOOK(6), LAVA_DEATH(7)
MATERIALS = {
    "default": 0,
    "grabbable": 1,
    "crumbling": 2,         # Maps to GRABBABLE_CRUMBLING
    "death": 3,             # Maps to DEATH (General kill zone)
    "wood": 4,
    "colored grabbable": 5, # Maps to COLORED_GRABBABLE
    "grapple hook": 6,      # Maps to GRAPPLE_HOOK (New!)
    "lava death": 7         # Maps to LAVA_DEATH (New!)
}
# --- END UPDATED MATERIALS ---


# Data structures for the editor's internal representation
@dataclass
class Vector:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

@dataclass
class Quaternion:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

@dataclass
class Color:
    r: float = 1.0
    g: float = 1.0
    b: float = 1.0
    a: float = 1.0

@dataclass
class SceneNode:
    # Common properties
    node_id: int = field(default_factory=lambda: 0)
    parent_id: int = 0
    node_type: str = "LevelNodeStatic" # LevelNodeStatic, LevelNodeStart, etc.
    shape: str = "cube" # For static, crumbling, and sign nodes
    
    position: Vector = field(default_factory=Vector)
    scale: Vector = field(default_factory=lambda: Vector(1.0, 1.0, 1.0))
    rotation: Quaternion = field(default_factory=Quaternion)
    
    # Static-specific properties
    material: str = "default"
    color: Color = field(default_factory=Color)
    
    # Crumbling-specific properties
    stable_time: float = 1.0
    respawn_time: float = 5.0
    
    # Start/Finish properties
    radius: float = 0.5

    # Sign properties
    text: str = "Enter Text Here"

    # Group properties
    children: list = field(default_factory=list) # List of child SceneNode objects


def dict_to_vector(d):
    return Vector(d.get('x', 0.0), d.get('y', 0.0), d.get('z', 0.0))

def dict_to_quaternion(d):
    return Quaternion(d.get('x', 0.0), d.get('y', 0.0), d.get('z', 0.0), d.get('w', 1.0))

def dict_to_color(d):
    return Color(d.get('r', 1.0), d.get('g', 1.0), d.get('b', 1.0), d.get('a', 1.0))

def node_from_dict(d, next_id):
    node = SceneNode(node_id=next_id)
    node_type_name = next(iter(d['Node'])) # e.g. 'staticResponse'
    node_data = d['Node'][node_type_name]
    
    # Determine type and set common properties
    if node_type_name == 'startResponse':
        node.node_type = "LevelNodeStart"
    elif node_type_name == 'finishResponse':
        node.node_type = "LevelNodeFinish"
    elif node_type_name == 'staticResponse':
        node.node_type = "LevelNodeStatic"
        node.material = {v: k for k, v in MATERIALS.items()}.get(node_data.get('material', 0), "default")
        if 'color' in node_data:
             node.color = dict_to_color(node_data['color'])
    elif node_type_name == 'crumblingResponse':
        node.node_type = "LevelNodeCrumbling"
        node.stable_time = node_data.get('stableTime', 1.0)
        node.respawn_time = node_data.get('respawnTime', 5.0)
    elif node_type_name == 'signResponse':
        node.node_type = "LevelNodeSign"
        node.text = node_data.get('text', "Enter Text Here")
        if 'color' in node_data:
             node.color = dict_to_color(node_data['color'])
    elif node_type_name == 'groupResponse':
        node.node_type = "LevelNodeGroup"
        # Recursively load children
        node.children = []
        for child_dict in node_data.get('childNodes', []):
            child_node = node_from_dict(child_dict, next_id)
            child_node.parent_id = node.node_id
            node.children.append(child_node)
    
    # Handle Start/Finish radius and common position/rotation/scale
    if node.node_type in ["LevelNodeStart", "LevelNodeFinish"]:
        node.radius = node_data.get('radius', 0.5)

    # Position, Rotation, Scale (if present)
    if 'position' in node_data:
        node.position = dict_to_vector(node_data['position'])
    if 'rotation' in node_data:
        node.rotation = dict_to_quaternion(node_data['rotation'])
    if 'scale' in node_data:
        node.scale = dict_to_vector(node_data['scale'])

    # Shape (if present)
    if 'shape' in node_data:
        node.shape = {v: k for k, v in SHAPES.items()}.get(node_data.get('shape', 1000), "cube")
    
    return node


# Conversion to JSON for saving
def vector_to_dict(v):
    return {'x': v.x, 'y': v.y, 'z': v.z}

def quaternion_to_dict(q):
    return {'x': q.x, 'y': q.y, 'z': q.z, 'w': q.w}

def color_to_dict(c):
    # Ensure alpha is always 1.0 for now if not explicitly set
    return {'r': c.r, 'g': c.g, 'b': c.b, 'a': c.a or 1.0}


def node_to_dict(node: SceneNode):
    node_content = {}
    
    if node.node_type == "LevelNodeStart":
        node_content = {
            "position": vector_to_dict(node.position),
            "rotation": quaternion_to_dict(node.rotation),
            "radius": node.radius
        }
        node_key = "startResponse"
    
    elif node.node_type == "LevelNodeFinish":
        node_content = {
            "position": vector_to_dict(node.position),
            "radius": node.radius
        }
        node_key = "finishResponse"

    elif node.node_type == "LevelNodeStatic":
        node_content = {
            "shape": SHAPES.get(node.shape, 1000),
            "material": MATERIALS.get(node.material, 0),
            "position": vector_to_dict(node.position),
            "scale": vector_to_dict(node.scale),
            "rotation": quaternion_to_dict(node.rotation),
            "color": color_to_dict(node.color)
        }
        node_key = "staticResponse"

    elif node.node_type == "LevelNodeCrumbling":
        node_content = {
            "shape": SHAPES.get(node.shape, 1000),
            "material": MATERIALS.get("crumbling", 2), # Must be GRABBABLE_CRUMBLING (2)
            "position": vector_to_dict(node.position),
            "scale": vector_to_dict(node.scale),
            "rotation": quaternion_to_dict(node.rotation),
            "stableTime": node.stable_time,
            "respawnTime": node.respawn_time
        }
        node_key = "crumblingResponse"

    elif node.node_type == "LevelNodeSign":
        # Note: Sign node has shape, position, scale, rotation, color, and text in the new proto
        node_content = {
            "shape": SHAPES.get(node.shape, 1000), # Using a default cube shape for signs
            "position": vector_to_dict(node.position),
            "scale": vector_to_dict(node.scale),
            "rotation": quaternion_to_dict(node.rotation),
            "color": color_to_dict(node.color),
            "text": node.text
        }
        node_key = "signResponse"
        
    elif node.node_type == "LevelNodeGroup":
        node_content = {
            "position": vector_to_dict(node.position),
            "rotation": quaternion_to_dict(node.rotation),
            "scale": vector_to_dict(node.scale),
            "childNodes": [node_to_dict(child) for child in node.children]
        }
        node_key = "groupResponse"
    
    else:
        # Should not happen
        return None 

    return {
        "id": node.node_id,
        "parentId": node.parent_id,
        "Node": {
            node_key: node_content
        }
    }


class LevelEditor(QMainWindow):
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GRAB Level Editor")
        self.setGeometry(100, 100, 1200, 800)
        
        self.next_node_id = 1
        self.scene_data = {
            'formatVersion': 1,
            'title': 'New Level',
            'creators': 'Unknown',
            'description': 'A fantastic GRAB level.',
            'complexity': 1,
            'maxCheckpointCount': 10,
            'ambienceSettings': {
                'skyZenithColor': {'r': 0.1, 'g': 0.1, 'b': 0.3, 'a': 1.0},
                'skyHorizonColor': {'r': 0.5, 'g': 0.5, 'b': 0.8, 'a': 1.0},
                'sunAltitude': 45.0,
                'sunAzimuth': 0.0,
                'sunSize': 1.0,
                'fogDDensity': 0.0
            },
            'levelNodes': []
        }
        self.level_file_path = None
        self._editing_node = None # The currently selected SceneNode object
        self.scene_nodes = [] # Flat list of all SceneNode objects in the scene

        self._initialize_ui()
        self._setup_actions()
        self._populate_default_scene()
        self._update_ui_from_scene()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.viewport.update)
        self.timer.start(16) # ~60 fps

    def _get_next_id(self):
        # Find the highest ID and increment
        def find_max_id(nodes):
            max_id = 0
            for node in nodes:
                max_id = max(max_id, node.node_id)
                if node.node_type == "LevelNodeGroup":
                    max_id = max(max_id, find_max_id(node.children))
            return max_id

        if not self.scene_nodes:
            self.next_node_id = 1
        else:
            self.next_node_id = find_max_id(self.scene_nodes) + 1
        return self.next_node_id

    def _initialize_ui(self):
        # Central Widget and Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        
        # Splitter for better resizing experience
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)

        # --- Left Panel (Controls) ---
        self.control_panel = QFrame()
        self.control_panel.setFrameShape(QFrame.StyledPanel)
        self.control_panel.setMinimumWidth(300)
        self.control_layout = QVBoxLayout(self.control_panel)
        
        self.tabs = QTabWidget()
        self.control_layout.addWidget(self.tabs)
        
        # Tab 1: Scene/Level Settings
        self.level_tab = QWidget()
        self.tabs.addTab(self.level_tab, "Level Settings")
        self.level_form = QFormLayout(self.level_tab)
        
        self.title_input = QLineEdit()
        self.creators_input = QLineEdit()
        self.description_input = QTextEdit()
        self.complexity_input = QSpinBox()
        self.complexity_input.setRange(1, 10)
        self.max_checkpoint_input = QSpinBox()
        self.max_checkpoint_input.setRange(0, 100)

        self.level_form.addRow("Title:", self.title_input)
        self.level_form.addRow("Creators:", self.creators_input)
        self.level_form.addRow("Description:", self.description_input)
        self.level_form.addRow("Complexity:", self.complexity_input)
        self.level_form.addRow("Max Checkpoints:", self.max_checkpoint_input)

        # Ambience Settings
        ambience_group = QFrame()
        ambience_layout = QFormLayout(ambience_group)
        self.level_form.addRow(QLabel("<b>Ambience Settings</b>"))
        self.level_form.addRow(ambience_group)
        
        self.sky_zenith_btn = QPushButton("Pick Sky Zenith Color")
        self.sky_horizon_btn = QPushButton("Pick Sky Horizon Color")
        self.sun_alt_input = QDoubleSpinBox(); self.sun_alt_input.setRange(0, 90); self.sun_alt_input.setDecimals(2)
        self.sun_azi_input = QDoubleSpinBox(); self.sun_azi_input.setRange(-180, 180); self.sun_azi_input.setDecimals(2)
        self.sun_size_input = QDoubleSpinBox(); self.sun_size_input.setRange(0.1, 10); self.sun_size_input.setDecimals(2)
        self.fog_density_input = QDoubleSpinBox(); self.fog_density_input.setRange(0, 10); self.fog_density_input.setDecimals(2)
        
        ambience_layout.addRow("Sky Zenith Color:", self.sky_zenith_btn)
        ambience_layout.addRow("Sky Horizon Color:", self.sky_horizon_btn)
        ambience_layout.addRow("Sun Altitude (deg):", self.sun_alt_input)
        ambience_layout.addRow("Sun Azimuth (deg):", self.sun_azi_input)
        ambience_layout.addRow("Sun Size:", self.sun_size_input)
        ambience_layout.addRow("Fog Density:", self.fog_density_input)

        # Connect level settings signals
        self.title_input.textChanged.connect(lambda: self._update_level_info('title', self.title_input.text()))
        self.creators_input.textChanged.connect(lambda: self._update_level_info('creators', self.creators_input.text()))
        self.description_input.textChanged.connect(lambda: self._update_level_info('description', self.description_input.toPlainText()))
        self.complexity_input.valueChanged.connect(lambda val: self._update_level_info('complexity', val))
        self.max_checkpoint_input.valueChanged.connect(lambda val: self._update_level_info('maxCheckpointCount', val))

        self.sky_zenith_btn.clicked.connect(lambda: self.on_pick_ambience_color('skyZenithColor'))
        self.sky_horizon_btn.clicked.connect(lambda: self.on_pick_ambience_color('skyHorizonColor'))
        self.sun_alt_input.valueChanged.connect(self._update_ambience_from_ui)
        self.sun_azi_input.valueChanged.connect(self._update_ambience_from_ui)
        self.sun_size_input.valueChanged.connect(self._update_ambience_from_ui)
        self.fog_density_input.valueChanged.connect(self._update_ambience_from_ui)


        # Tab 2: Node Editor
        self.node_tab = QWidget()
        self.tabs.addTab(self.node_tab, "Node Properties")
        self.node_layout = QVBoxLayout(self.node_tab)
        
        self.node_label = QLabel("Select a Node to Edit Properties")
        self.node_layout.addWidget(self.node_label)

        self.node_form = QFormLayout()
        self.node_layout.addLayout(self.node_form)
        
        # Node properties fields (will be populated/cleared dynamically)
        self.pos_x_input = QDoubleSpinBox(); self.pos_x_input.setRange(-9999, 9999); self.pos_x_input.setDecimals(3)
        self.pos_y_input = QDoubleSpinBox(); self.pos_y_input.setRange(-9999, 9999); self.pos_y_input.setDecimals(3)
        self.pos_z_input = QDoubleSpinBox(); self.pos_z_input.setRange(-9999, 9999); self.pos_z_input.setDecimals(3)
        
        self.scale_x_input = QDoubleSpinBox(); self.scale_x_input.setRange(0.001, 9999); self.scale_x_input.setDecimals(3)
        self.scale_y_input = QDoubleSpinBox(); self.scale_y_input.setRange(0.001, 9999); self.scale_y_input.setDecimals(3)
        self.scale_z_input = QDoubleSpinBox(); self.scale_z_input.setRange(0.001, 9999); self.scale_z_input.setDecimals(3)

        self.rot_x_input = QDoubleSpinBox(); self.rot_x_input.setRange(-180, 180); self.rot_x_input.setDecimals(3)
        self.rot_y_input = QDoubleSpinBox(); self.rot_y_input.setRange(-180, 180); self.rot_y_input.setDecimals(3)
        self.rot_z_input = QDoubleSpinBox(); self.rot_z_input.setRange(-180, 180); self.rot_z_input.setDecimals(3)
        
        self.shape_selector = QComboBox()
        self.shape_selector.addItems(SHAPES.keys())

        self.material_selector = QComboBox()
        self.material_selector.addItems(MATERIALS.keys())
        
        self.color_btn = QPushButton("Pick Color")
        self.radius_input = QDoubleSpinBox(); self.radius_input.setRange(0.01, 999); self.radius_input.setDecimals(3)
        self.text_input = QLineEdit()
        self.stable_time_input = QDoubleSpinBox(); self.stable_time_input.setRange(0.1, 999); self.stable_time_input.setDecimals(2)
        self.respawn_time_input = QDoubleSpinBox(); self.respawn_time_input.setRange(0.1, 999); self.respawn_time_input.setDecimals(2)
        
        # Connect node property signals
        self.pos_x_input.valueChanged.connect(lambda val: self._update_node_vector('position', 'x', val))
        self.pos_y_input.valueChanged.connect(lambda val: self._update_node_vector('position', 'y', val))
        self.pos_z_input.valueChanged.connect(lambda val: self._update_node_vector('position', 'z', val))
        
        self.scale_x_input.valueChanged.connect(lambda val: self._update_node_vector('scale', 'x', val))
        self.scale_y_input.valueChanged.connect(lambda val: self._update_node_vector('scale', 'y', val))
        self.scale_z_input.valueChanged.connect(lambda val: self._update_node_vector('scale', 'z', val))

        self.rot_x_input.valueChanged.connect(lambda val: self._update_node_rotation(val, 'x'))
        self.rot_y_input.valueChanged.connect(lambda val: self._update_node_rotation(val, 'y'))
        self.rot_z_input.valueChanged.connect(lambda val: self._update_node_rotation(val, 'z'))

        self.shape_selector.currentTextChanged.connect(lambda text: self._update_node_prop('shape', text))
        self.material_selector.currentTextChanged.connect(lambda text: self._update_node_prop('material', text))
        self.color_btn.clicked.connect(lambda: self.on_pick_node_color('color'))
        self.radius_input.valueChanged.connect(lambda val: self._update_node_prop('radius', val))
        self.text_input.textChanged.connect(lambda text: self._update_node_prop('text', text))
        self.stable_time_input.valueChanged.connect(lambda val: self._update_node_prop('stable_time', val))
        self.respawn_time_input.valueChanged.connect(lambda val: self._update_node_prop('respawn_time', val))
        

        self.node_layout.addStretch(1)


        # Tab 3: Scene Tree View
        self.tree_tab = QWidget()
        self.tabs.addTab(self.tree_tab, "Scene Hierarchy")
        self.tree_layout = QVBoxLayout(self.tree_tab)

        # Node Creation Buttons
        create_buttons_layout = QHBoxLayout()
        self.add_cube_btn = QPushButton("Add Cube")
        self.add_sphere_btn = QPushButton("Add Sphere")
        self.add_start_btn = QPushButton("Add Start")
        self.add_finish_btn = QPushButton("Add Finish")
        create_buttons_layout.addWidget(self.add_cube_btn)
        create_buttons_layout.addWidget(self.add_sphere_btn)
        create_buttons_layout.addWidget(self.add_start_btn)
        create_buttons_layout.addWidget(self.add_finish_btn)
        self.tree_layout.addLayout(create_buttons_layout)

        self.node_list = QListWidget()
        self.tree_layout.addWidget(self.node_list)

        # Other Node Actions
        action_buttons_layout = QHBoxLayout()
        self.delete_btn = QPushButton("Delete Node")
        self.duplicate_btn = QPushButton("Duplicate Node")
        action_buttons_layout.addWidget(self.delete_btn)
        action_buttons_layout.addWidget(self.duplicate_btn)
        self.tree_layout.addLayout(action_buttons_layout)

        # Connect tree view signals
        self.node_list.itemClicked.connect(self.on_node_selected)
        self.add_cube_btn.clicked.connect(lambda: self.add_new_node("LevelNodeStatic", "cube"))
        self.add_sphere_btn.clicked.connect(lambda: self.add_new_node("LevelNodeStatic", "sphere"))
        self.add_start_btn.clicked.connect(lambda: self.add_new_node("LevelNodeStart", "sphere"))
        self.add_finish_btn.clicked.connect(lambda: self.add_new_node("LevelNodeFinish", "sphere"))
        self.delete_btn.clicked.connect(self.delete_selected_node)
        self.duplicate_btn.clicked.connect(self.duplicate_selected_node)


        self.splitter.addWidget(self.control_panel)
        
        # --- Right Panel (3D Viewport) ---
        self.viewport = Viewport(self)
        self.splitter.addWidget(self.viewport)
        self.splitter.setSizes([300, 900]) # Initial split

    def _setup_actions(self):
        # File Menu
        file_menu = self.menuBar().addMenu("&File")
        
        new_action = QAction("&New", self); new_action.triggered.connect(self.new_level)
        open_action = QAction("&Open...", self); open_action.triggered.connect(self.open_level)
        save_action = QAction("&Save", self); save_action.triggered.connect(lambda: self.save_level(False))
        save_as_action = QAction("Save &As...", self); save_as_action.triggered.connect(lambda: self.save_level(True))

        file_menu.addAction(new_action)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(save_action)
        file_menu.addAction(save_as_action)

    def _populate_default_scene(self):
        # Add a default start and finish node
        self.add_new_node("LevelNodeStart", "sphere", Vector(0, 0.5, 0))
        self.add_new_node("LevelNodeFinish", "sphere", Vector(0, 5, 0))
        self.add_new_node("LevelNodeStatic", "cube", Vector(0, 0, -2), Vector(10, 0.5, 10), "default") # Ground

    def _update_ui_from_scene(self):
        # Update Level Info Tab
        info = self.scene_data
        self.title_input.setText(info.get('title', ''))
        self.creators_input.setText(info.get('creators', ''))
        self.description_input.setText(info.get('description', ''))
        self.complexity_input.setValue(info.get('complexity', 1))
        self.max_checkpoint_input.setValue(info.get('maxCheckpointCount', 10))
        
        amb = info.get('ambienceSettings', {})
        self.sun_alt_input.setValue(amb.get('sunAltitude', 45.0))
        self.sun_azi_input.setValue(amb.get('sunAzimuth', 0.0))
        self.sun_size_input.setValue(amb.get('sunSize', 1.0))
        self.fog_density_input.setValue(amb.get('fogDDensity', 0.0))

        # Update Node List
        self.node_list.clear()
        
        def populate_list(nodes, indent=""):
            for node in nodes:
                item = QListWidgetItem(f"{indent}[ID: {node.node_id}] {node.node_type.replace('LevelNode', '')} ({node.shape}, {node.material or node.radius})")
                item.setData(Qt.UserRole, node.node_id)
                self.node_list.addItem(item)
                if node.node_type == "LevelNodeGroup" and node.children:
                    populate_list(node.children, indent + "  ")

        populate_list(self.scene_nodes)
        self.on_node_selected(None) # Clear node editor UI

    def _find_node_by_id(self, node_id, nodes=None):
        if nodes is None:
            nodes = self.scene_nodes
            
        for node in nodes:
            if node.node_id == node_id:
                return node
            if node.node_type == "LevelNodeGroup":
                found = self._find_node_by_id(node_id, node.children)
                if found:
                    return found
        return None

    def _remove_node_by_id(self, node_id, nodes=None):
        if nodes is None:
            nodes = self.scene_nodes
            
        for i, node in enumerate(nodes):
            if node.node_id == node_id:
                del nodes[i]
                return True
            if node.node_type == "LevelNodeGroup":
                if self._remove_node_by_id(node_id, node.children):
                    return True
        return False
        
    def _update_level_info(self, key, value):
        self.scene_data[key] = value

    def on_pick_ambience_color(self, key: str):
        amb = self.scene_data.get('ambienceSettings', {})
        existing = amb.get(key, {'r': 0.5, 'g': 0.5, 'b': 0.5, 'a': 1.0})
        
        r = int(existing.get('r', 0.5) * 255)
        g = int(existing.get('g', 0.5) * 255)
        b = int(existing.get('b', 0.5) * 255)
        col = QColor(r, g, b)
        
        c = QColorDialog.getColor(col, self, f"Pick Ambience {key} Color")
        if not c.isValid():
            return
            
        r, g, b, a = c.redF(), c.greenF(), c.blueF(), c.alphaF()
        self.scene_data['ambienceSettings'][key] = {'r': r, 'g': g, 'b': b, 'a': a}
        self.viewport.update()

    def on_pick_node_color(self, color_field: str):
        node = self._editing_node
        if not node:
            return
        
        # Determine which color property to use
        color_obj = getattr(node, color_field) if hasattr(node, color_field) else Color()
        
        r = int(color_obj.r * 255)
        g = int(color_obj.g * 255)
        b = int(color_obj.b * 255)
        col = QColor(r, g, b)
        
        c = QColorDialog.getColor(col, self, f"Pick Node {color_field} Color")
        if not c.isValid():
            return
            
        # Update the color field on the SceneNode object
        setattr(node, color_field, Color(c.redF(), c.greenF(), c.blueF(), c.alphaF()))
        self.viewport.update()

    def _update_ambience_from_ui(self):
        amb = self.scene_data.get('ambienceSettings', {})
        amb['sunAltitude'] = self.sun_alt_input.value()
        amb['sunAzimuth'] = self.sun_azi_input.value()
        amb['sunSize'] = self.sun_size_input.value()
        amb['fogDDensity'] = self.fog_density_input.value()
        self.viewport.update()


    def _update_node_prop(self, prop, value):
        node = self._editing_node
        if node:
            if prop == 'shape':
                # Only static, crumbling, and sign nodes have shapes in the new proto
                if node.node_type in ["LevelNodeStatic", "LevelNodeCrumbling", "LevelNodeSign"]:
                    setattr(node, prop, value)
            elif prop == 'material':
                # Only LevelNodeStatic has a general material property
                if node.node_type == "LevelNodeStatic":
                    setattr(node, prop, value)
            elif prop == 'text':
                if node.node_type == "LevelNodeSign":
                    setattr(node, prop, value)
            elif prop in ['stable_time', 'respawn_time']:
                if node.node_type == "LevelNodeCrumbling":
                    setattr(node, prop, value)
            elif prop == 'radius':
                if node.node_type in ["LevelNodeStart", "LevelNodeFinish"]:
                    setattr(node, prop, value)

            self._update_ui_from_scene() # Refresh list to show name change
            self.viewport.update()


    def _update_node_vector(self, prop_name, coord, value):
        node = self._editing_node
        if node and hasattr(node, prop_name):
            vector = getattr(node, prop_name)
            setattr(vector, coord, value)
            self.viewport.update()
            
    def _update_node_rotation(self, value, axis):
        node = self._editing_node
        if node:
            # We treat UI input as Euler angles (in degrees) for simplicity
            # For now, we only update the component based on input, 
            # as proper Quaternion management in a UI is complex.
            # For better UX, we'll store the Euler angle in degrees in the corresponding Quaternion field 
            # and let the renderer handle the actual rotation logic.
            if axis == 'x':
                node.rotation.x = value # Using x as pitch (rotation around X)
            elif axis == 'y':
                node.rotation.y = value # Using y as yaw (rotation around Y)
            elif axis == 'z':
                node.rotation.z = value # Using z as roll (rotation around Z)
            
            self.viewport.update()


    def on_node_selected(self, item):
        # Clear existing form elements
        for i in reversed(range(self.node_form.count())):
            widget = self.node_form.itemAt(i).widget()
            if widget:
                widget.setParent(None)
                
        self._editing_node = None

        if item:
            node_id = item.data(Qt.UserRole)
            node = self._find_node_by_id(node_id)
            self._editing_node = node
            self.node_label.setText(f"Editing Node ID: {node.node_id} ({node.node_type.replace('LevelNode', '')})")
            self.tabs.setCurrentIndex(1) # Switch to Node Properties tab

            if not node: return

            # Position, Scale, Rotation (Common to most nodes)
            self.node_form.addRow("<b>Transforms</b>", QLabel(""))
            self.node_form.addRow("Pos X:", self.pos_x_input); self.pos_x_input.setValue(node.position.x)
            self.node_form.addRow("Pos Y:", self.pos_y_input); self.pos_y_input.setValue(node.position.y)
            self.node_form.addRow("Pos Z:", self.pos_z_input); self.pos_z_input.setValue(node.position.z)

            if node.node_type not in ["LevelNodeStart", "LevelNodeFinish"]:
                self.node_form.addRow("Scale X:", self.scale_x_input); self.scale_x_input.setValue(node.scale.x)
                self.node_form.addRow("Scale Y:", self.scale_y_input); self.scale_y_input.setValue(node.scale.y)
                self.node_form.addRow("Scale Z:", self.scale_z_input); self.scale_z_input.setValue(node.scale.z)

            self.node_form.addRow("Rot X (°):", self.rot_x_input); self.rot_x_input.setValue(node.rotation.x)
            self.node_form.addRow("Rot Y (°):", self.rot_y_input); self.rot_y_input.setValue(node.rotation.y)
            self.node_form.addRow("Rot Z (°):", self.rot_z_input); self.rot_z_input.setValue(node.rotation.z)
            self.node_form.addRow(QLabel("---"))
            
            # Node Type Specific Properties
            if node.node_type in ["LevelNodeStatic", "LevelNodeCrumbling", "LevelNodeSign"]:
                self.node_form.addRow("Shape:", self.shape_selector)
                self.shape_selector.setCurrentText(node.shape)
                self.node_form.addRow(QLabel("---"))

            if node.node_type == "LevelNodeStatic":
                self.node_form.addRow("Material:", self.material_selector)
                self.material_selector.setCurrentText(node.material)
                self.node_form.addRow("Color:", self.color_btn)

            elif node.node_type == "LevelNodeCrumbling":
                self.node_form.addRow("Stable Time:", self.stable_time_input); self.stable_time_input.setValue(node.stable_time)
                self.node_form.addRow("Respawn Time:", self.respawn_time_input); self.respawn_time_input.setValue(node.respawn_time)
                
            elif node.node_type in ["LevelNodeStart", "LevelNodeFinish"]:
                self.node_form.addRow("Radius:", self.radius_input); self.radius_input.setValue(node.radius)
                
            elif node.node_type == "LevelNodeSign":
                self.node_form.addRow("Text:", self.text_input); self.text_input.setText(node.text)
                self.node_form.addRow("Color:", self.color_btn)


    def add_new_node(self, node_type, shape, position=None, scale=None, material="default"):
        new_id = self._get_next_id()
        
        if position is None: position = Vector(self.viewport.camera_pos.x, self.viewport.camera_pos.y, self.viewport.camera_pos.z - 5)
        if scale is None: scale = Vector(1.0, 1.0, 1.0)

        new_node = SceneNode(
            node_id=new_id,
            node_type=node_type,
            shape=shape,
            position=position,
            scale=scale,
            material=material
        )
        
        # Adjust default for specific types
        if node_type == "LevelNodeStart":
            new_node.scale = Vector(1.0, 1.0, 1.0)
            new_node.material = "default" # Start/Finish don't use material in the same way
        elif node_type == "LevelNodeFinish":
            new_node.scale = Vector(1.0, 1.0, 1.0)
            new_node.material = "default"
        
        self.scene_nodes.append(new_node)
        self._update_ui_from_scene()
        self.viewport.update()
        
        # Select the newly created node
        for i in range(self.node_list.count()):
            item = self.node_list.item(i)
            if item.data(Qt.UserRole) == new_id:
                self.node_list.setCurrentItem(item)
                self.on_node_selected(item)
                break


    def delete_selected_node(self):
        current_item = self.node_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Warning", "Please select a node to delete.")
            return

        node_id = current_item.data(Qt.UserRole)
        if QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete Node ID {node_id}?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._remove_node_by_id(node_id)
            self._editing_node = None # Clear editor state
            self._update_ui_from_scene()
            self.viewport.update()

    def duplicate_selected_node(self):
        node = self._editing_node
        if not node:
            QMessageBox.warning(self, "Warning", "Please select a node to duplicate.")
            return

        # Deep copy the node object
        new_node = copy.deepcopy(node)
        new_node.node_id = self._get_next_id()
        new_node.parent_id = 0 # Duplicated nodes become root nodes for simplicity

        # Move the duplicated node slightly
        new_node.position.x += 1.0
        new_node.position.y += 1.0
        
        # Recursively update child IDs if it's a group
        def update_child_ids(children, new_parent_id):
            for child in children:
                old_id = child.node_id
                child.node_id = self._get_next_id()
                child.parent_id = new_parent_id
                
                if child.node_type == "LevelNodeGroup":
                    update_child_ids(child.children, child.node_id)
        
        if new_node.node_type == "LevelNodeGroup":
            update_child_ids(new_node.children, new_node.node_id)

        self.scene_nodes.append(new_node)
        self._update_ui_from_scene()
        self.viewport.update()


    def new_level(self):
        if QMessageBox.question(self, "Confirm New Level", "Start a new level? Unsaved changes will be lost.",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.scene_data = {
                'formatVersion': 1,
                'title': 'New Level',
                'creators': 'Unknown',
                'description': 'A fantastic GRAB level.',
                'complexity': 1,
                'maxCheckpointCount': 10,
                'ambienceSettings': {
                    'skyZenithColor': {'r': 0.1, 'g': 0.1, 'b': 0.3, 'a': 1.0},
                    'skyHorizonColor': {'r': 0.5, 'g': 0.5, 'b': 0.8, 'a': 1.0},
                    'sunAltitude': 45.0,
                    'sunAzimuth': 0.0,
                    'sunSize': 1.0,
                    'fogDDensity': 0.0
                },
                'levelNodes': []
            }
            self.scene_nodes = []
            self.level_file_path = None
            self._editing_node = None
            self._populate_default_scene()
            self._update_ui_from_scene()
            QMessageBox.information(self, "Info", "New level created.")


    def open_level(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Level", "", "GRAB Level JSON (*.json *.level);;All Files (*)")
        if file_name:
            try:
                with open(file_name, 'r') as f:
                    data = json.load(f)
                    
                self.scene_data = data
                self.scene_nodes = []
                self.level_file_path = file_name
                self._editing_node = None
                
                # Load nodes recursively
                max_id = 0
                for node_dict in data.get('levelNodes', []):
                    new_node = node_from_dict(node_dict, self._get_next_id())
                    self.scene_nodes.append(new_node)
                
                self._update_ui_from_scene()
                QMessageBox.information(self, "Info", f"Successfully loaded {file_name}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open level file: {e}")

    def save_level(self, save_as):
        if self.level_file_path is None or save_as:
            file_name, _ = QFileDialog.getSaveFileName(self, "Save Level", self.level_file_path or "", "GRAB Level JSON (*.json *.level);;All Files (*)")
            if not file_name:
                return
            self.level_file_path = file_name
        
        try:
            # 1. Update level info from UI one last time
            self._update_level_info('title', self.title_input.text())
            self._update_level_info('creators', self.creators_input.text())
            self._update_level_info('description', self.description_input.toPlainText())
            self._update_level_info('complexity', self.complexity_input.value())
            self._update_level_info('maxCheckpointCount', self.max_checkpoint_input.value())
            self._update_ambience_from_ui()

            # 2. Convert internal SceneNodes back to protobuf-compatible dictionary structure
            node_dicts = [node_to_dict(node) for node in self.scene_nodes]
            self.scene_data['levelNodes'] = node_dicts

            # 3. Write to file
            with open(self.level_file_path, 'w') as f:
                json.dump(self.scene_data, f, indent=4)
            
            QMessageBox.information(self, "Info", f"Level successfully saved to {self.level_file_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save level file: {e}")


# --- OpenGL Viewport Class ---

class Viewport(QOpenGLWidget):
    
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        
        self.camera_pos = Vector(0, 3, 10)
        self.camera_pitch = -15
        self.camera_yaw = -90
        
        self.last_mouse_pos = QPoint()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        
        self.movement_speed = 0.2
        self.keys_pressed = set()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.move_camera)
        self.timer.start(16)

    def initializeGL(self):
        glClearColor(0.8, 0.8, 0.8, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [0, 10, 0, 1])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [1, 1, 1, 1])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.3, 0.3, 0.3, 1])
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glEnable(GL_COLOR_MATERIAL)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(60.0, w/h, 0.1, 1000.0)
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        
        # Apply camera rotation and translation
        glRotatef(self.camera_pitch, 1.0, 0.0, 0.0)
        glRotatef(self.camera_yaw, 0.0, 1.0, 0.0)
        glTranslatef(-self.camera_pos.x, -self.camera_pos.y, -self.camera_pos.z)
        
        # Draw all nodes
        self._draw_scene()
        
        # Draw Grid
        self._draw_grid()

    def _draw_grid(self, size=20, step=1):
        glDisable(GL_LIGHTING)
        glColor3f(0.5, 0.5, 0.5)
        glBegin(GL_LINES)
        
        # Draw lines parallel to X-axis
        for i in range(-size, size + 1, step):
            glVertex3f(i, 0.0, -size)
            glVertex3f(i, 0.0, size)
            
        # Draw lines parallel to Z-axis
        for j in range(-size, size + 1, step):
            glVertex3f(-size, 0.0, j)
            glVertex3f(size, 0.0, j)
            
        glEnd()
        glEnable(GL_LIGHTING)

    def _draw_scene(self):
        
        def draw_node_recursive(node: SceneNode, is_selected):
            
            # Save parent transformation
            glPushMatrix()
            
            # Apply node transformation
            glTranslatef(node.position.x, node.position.y, node.position.z)

            # Convert Quaternion rotation to GL rotation (simplified for editor preview)
            # This is a highly simplified representation and should be replaced with a proper
            # Quaterion -> Matrix conversion in a real engine/editor.
            # We are using the "x, y, z" of the quaternion as Euler angles in degrees for ease of editing.
            glRotatef(node.rotation.x, 1.0, 0.0, 0.0) 
            glRotatef(node.rotation.y, 0.0, 1.0, 0.0) 
            glRotatef(node.rotation.z, 0.0, 0.0, 1.0)
            
            
            # Draw Node Content (only for non-group nodes)
            if node.node_type != "LevelNodeGroup":
                
                # Highlight if selected
                if is_selected:
                    glDisable(GL_LIGHTING)
                    glColor3f(1.0, 1.0, 0.0) # Yellow highlight
                    glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
                    glLineWidth(3.0)
                
                # Set color and material
                c = node.color
                material_name = node.material
                
                # Material Visual Overrides
                if node.node_type == "LevelNodeStart":
                    glColor4f(0.0, 1.0, 0.0, 0.5) # Green, transparent
                    glDisable(GL_LIGHTING)
                    glEnable(GL_BLEND)
                    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                elif node.node_type == "LevelNodeFinish":
                    glColor4f(1.0, 0.0, 1.0, 0.5) # Magenta, transparent
                    glDisable(GL_LIGHTING)
                    glEnable(GL_BLEND)
                    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                elif material_name == "crumbling":
                    glColor4f(1.0, 0.5, 0.0, 1.0) # Orange
                elif material_name == "death" or material_name == "lava death": # Updated for new materials
                    glColor4f(1.0, 0.0, 0.0, 1.0) # Red
                elif material_name == "grapple hook": # Updated for new materials
                    glColor4f(0.0, 0.8, 0.0, 1.0) # Bright Green
                else:
                    glColor4f(c.r, c.g, c.b, c.a)
                    glEnable(GL_LIGHTING)


                # Scale and Draw
                glScalef(node.scale.x, node.scale.y, node.scale.z)

                if node.shape == "cube":
                    glBegin(GL_QUADS)
                    # Simple unit cube definition (no normals/textures for mock)
                    # Face 1
                    glVertex3f(-0.5, -0.5, 0.5)
                    glVertex3f(0.5, -0.5, 0.5)
                    glVertex3f(0.5, 0.5, 0.5)
                    glVertex3f(-0.5, 0.5, 0.5)
                    # Face 2
                    glVertex3f(-0.5, -0.5, -0.5)
                    glVertex3f(0.5, -0.5, -0.5)
                    glVertex3f(0.5, 0.5, -0.5)
                    glVertex3f(-0.5, 0.5, -0.5)
                    # ... (missing all 6 faces for brevity, but a full cube drawing would be here)
                    glEnd()
                    glutWireCube(1.0) # Using wireframe as placeholder for real cube rendering
                    
                elif node.shape == "sphere":
                    # For Start/Finish, scale is ignored and radius is used
                    if node.node_type in ["LevelNodeStart", "LevelNodeFinish"]:
                        gluSphere(gluNewQuadric(), node.radius / max(node.scale.x, node.scale.y, node.scale.z), 16, 16)
                    else:
                        # Draw unit sphere (scale handles dimensions)
                        gluSphere(gluNewQuadric(), 0.5, 16, 16)
                        
                # End highlight
                if is_selected:
                    glEnable(GL_LIGHTING)
                    glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
                    glLineWidth(1.0)
                    glDisable(GL_BLEND)
                    
            # Recursively draw children (for groups)
            if node.node_type == "LevelNodeGroup":
                for child in node.children:
                    draw_node_recursive(child, self.main_window._editing_node == child)


            # Restore parent transformation
            glPopMatrix()


        selected_id = self.main_window._editing_node.node_id if self.main_window._editing_node else -1

        for node in self.main_window.scene_nodes:
            draw_node_recursive(node, node.node_id == selected_id)


    def mousePressEvent(self, event):
        self.last_mouse_pos = event.pos()

    def mouseMoveEvent(self, event):
        dx = event.x() - self.last_mouse_pos.x()
        dy = event.y() - self.last_mouse_pos.y()
        
        if event.buttons() & Qt.LeftButton:
            # Rotate camera
            self.camera_yaw += dx * 0.2
            self.camera_pitch += dy * 0.2
            
            # Clamp pitch
            self.camera_pitch = max(-89.0, min(89.0, self.camera_pitch))
            
            self.update()
            
        self.last_mouse_pos = event.pos()

    def wheelEvent(self, event):
        # Zoom in/out by moving along the camera's forward vector
        delta = event.angleDelta().y() / 120
        rad_yaw = math.radians(self.camera_yaw)
        rad_pitch = math.radians(self.camera_pitch)
        
        move_x = math.cos(rad_yaw) * math.cos(rad_pitch) * delta * self.movement_speed * 10
        move_y = -math.sin(rad_pitch) * delta * self.movement_speed * 10
        move_z = -math.sin(rad_yaw) * math.cos(rad_pitch) * delta * self.movement_speed * 10
        
        self.camera_pos.x -= move_x
        self.camera_pos.y -= move_y
        self.camera_pos.z -= move_z
        
        self.update()


    def keyPressEvent(self, event):
        if event.key() != 0: # 0 means Key_unknown (e.g. modifier key pressed alone)
            self.keys_pressed.add(event.key())

    def keyReleaseEvent(self, event):
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())

    def move_camera(self):
        # Based on keys_pressed, calculate movement
        move_vector = Vector(0, 0, 0)
        
        # Calculate camera direction vectors
        rad_yaw = math.radians(self.camera_yaw)
        rad_pitch = math.radians(self.camera_pitch)
        
        # Forward/Backward
        forward_x = math.cos(rad_yaw) * math.cos(rad_pitch)
        forward_y = -math.sin(rad_pitch)
        forward_z = -math.sin(rad_yaw) * math.cos(rad_pitch)
        
        # Strafe
        strafe_x = math.sin(rad_yaw)
        strafe_z = math.cos(rad_yaw)

        # Movement keys (W, S, A, D, Q, E)
        if Qt.Key_W in self.keys_pressed: # Forward
            move_vector.x += forward_x
            move_vector.y += forward_y
            move_vector.z += forward_z
        if Qt.Key_S in self.keys_pressed: # Backward
            move_vector.x -= forward_x
            move_vector.y -= forward_y
            move_vector.z -= forward_z
        if Qt.Key_A in self.keys_pressed: # Strafe Left
            move_vector.x -= strafe_x
            move_vector.z -= strafe_z
        if Qt.Key_D in self.keys_pressed: # Strafe Right
            move_vector.x += strafe_x
            move_vector.z += strafe_z
        if Qt.Key_E in self.keys_pressed: # Up
            self.camera_pos.y += self.movement_speed
        if Qt.Key_Q in self.keys_pressed: # Down
            self.camera_pos.y -= self.movement_speed
            
        # Apply movement
        if move_vector.x != 0 or move_vector.y != 0 or move_vector.z != 0:
            
            # Normalize movement vector to ensure consistent speed regardless of how many keys are pressed
            mag = math.sqrt(move_vector.x**2 + move_vector.y**2 + move_vector.z**2)
            if mag > 0:
                self.camera_pos.x += move_vector.x / mag * self.movement_speed
                self.camera_pos.y += move_vector.y / mag * self.movement_speed
                self.camera_pos.z += move_vector.z / mag * self.movement_speed
            
            self.update() # Request redraw


if __name__ == '__main__':
    # Add a fallback for glut functions if not available (like on some PySide/Qt setups)
    try:
        from OpenGL.GLUT import glutInit, glutWireCube
        glutInit(sys.argv)
    except Exception:
        # Define a mock glutWireCube function if glut is missing
        def glutWireCube(size):
            half = size / 2.0
            glBegin(GL_LINES)
            # Define 12 edges of a cube
            # Bottom face
            glVertex3f(-half, -half, -half); glVertex3f(half, -half, -half)
            glVertex3f(half, -half, -half); glVertex3f(half, -half, half)
            glVertex3f(half, -half, half); glVertex3f(-half, -half, half)
            glVertex3f(-half, -half, half); glVertex3f(-half, -half, -half)
            # Top face
            glVertex3f(-half, half, -half); glVertex3f(half, half, -half)
            glVertex3f(half, half, -half); glVertex3f(half, half, half)
            glVertex3f(half, half, half); glVertex3f(-half, half, half)
            glVertex3f(-half, half, half); glVertex3f(-half, half, -half)
            # Connecting pillars
            glVertex3f(-half, -half, -half); glVertex3f(-half, half, -half)
            glVertex3f(half, -half, -half); glVertex3f(half, half, -half)
            glVertex3f(half, -half, half); glVertex3f(half, half, half)
            glVertex3f(-half, -half, half); glVertex3f(-half, half, half)
            glEnd()
        # Fallback for gluSphere's quadric initialization/drawing
        class MockQuadric:
            def __init__(self): pass
        def gluNewQuadric(): return MockQuadric()
        def gluSphere(quadric, radius, slices, stacks):
            glPushMatrix()
            # Approximation of a sphere with a dodecahedron (not perfect, but better than nothing)
            # This is extremely simplified and would render badly, but prevents crashing
            glTranslatef(0.0, 0.0, 0.0)
            glutWireCube(radius * 2) # Use cube as sphere approximation for no-glut env
            glPopMatrix()
            

    app = QApplication(sys.argv)
    editor = LevelEditor()
    editor.show()
    sys.exit(app.exec())
