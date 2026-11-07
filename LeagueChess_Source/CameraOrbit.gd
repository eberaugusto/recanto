extends Node3D
@export var sensibilidade_mouse = 0.005
@export var velocidade_zoom = 3.0
@export var zoom_min = 5.0
@export var zoom_max = 35.0
@onready var camera = $Camera3D
var zoom_atual = 18.0
var centro_tabuleiro = Vector3(7.0, 0.0, 7.0)
func _ready():
    global_position = centro_tabuleiro
    rotation_degrees.x = -45
    camera.position.z = zoom_atual
func _input(event):
    if event is InputEventMouseMotion and Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT):
        rotation.y -= event.relative.x * sensibilidade_mouse
        rotation.x -= event.relative.y * sensibilidade_mouse
        rotation.x = clamp(rotation.x, deg_to_rad(-85), deg_to_rad(-5))
    if event is InputEventMouseButton and event.pressed:
        var mudanca_zoom = 0.0
        if event.button_index == MOUSE_BUTTON_WHEEL_UP: mudanca_zoom = -velocidade_zoom
        elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN: mudanca_zoom = velocidade_zoom
        if mudanca_zoom != 0.0:
            zoom_atual = clamp(zoom_atual + mudanca_zoom, zoom_min, zoom_max)
            var viewport = get_viewport()
            var mouse_pos = viewport.get_mouse_position()
            var origem = camera.project_ray_origin(mouse_pos)
            var direcao = camera.project_ray_normal(mouse_pos)
            if direcao.y != 0:
                var t = -origem.y / direcao.y
                var ponto_chao = origem + direcao * t
                if mudanca_zoom < 0: global_position = global_position.lerp(ponto_chao, 0.15)
                else: global_position = global_position.lerp(centro_tabuleiro, 0.15)
            var tween = create_tween()
            tween.tween_property(camera, "position:z", zoom_atual, 0.15)
