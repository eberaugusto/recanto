extends Control
@onready var option_branca = $VBoxContainer/HBoxBranca/OptionBranca
@onready var option_preta = $VBoxContainer/HBoxPreta/OptionPreta
@onready var txt_ip = $VBoxContainer/HBoxIP/LineEditIP
func _ready():
	var faccoes = ["Demacia", "Noxus", "Ionia", "Ilha das Sombras"]
	for f in faccoes:
		option_branca.add_item(f)
		option_preta.add_item(f)
	option_preta.select(1)
func _on_btn_jogar_pressed():
	GameManager.faccao_branca = option_branca.get_item_text(option_branca.selected)
	GameManager.faccao_preta = option_preta.get_item_text(option_preta.selected)
	GameManager.ip_conexao = txt_ip.text
	get_tree().change_scene_to_file("res://Jogo.tscn")
func _on_btn_host_pressed():
	_on_btn_jogar_pressed()
	MultiplayerManager.criar_host()
func _on_btn_conectar_pressed():
	_on_btn_jogar_pressed()
	MultiplayerManager.conectar_cliente(GameManager.ip_conexao)
