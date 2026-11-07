extends Node3D

const TAMANHO_CASA = 2.0 
var matriz = {} 

@export var imagem_fundo: Texture2D

var peca_selecionada = null
var pos_selecionada = Vector2(-1, -1)
var turno_atual = "b"

var modelos_pecas = {}
var banco_faccoes = {
	"Demacia": {
		"bispo_1": {"caminho": "res://Modelos/fiora.glb", "nome": "Fiora", "funcao": "Bispo", "anims": {"idle": "Fiora_Idle1_anm", "run": "Run_Fast", "attack": "Crit", "death": "Death"}},
		"bispo_2": {"caminho": "res://Modelos/xin_zhao.glb", "nome": "Xin Zhao", "funcao": "Bispo", "anims": {"idle": "Idle_Var02", "run": "RunIn", "attack": "Attack2_ToIdle", "death": "Death"}},
		"rainha": {"caminho": "res://Modelos/kayle.glb", "nome": "Kayle", "funcao": "Rainha", "anims": {"idle": "Idle1_Base", "run": "Run_Homeguard", "attack": "Kayle_Attack2", "death": "Death"}},
		"torre_1": {"caminho": "res://Modelos/garen.glb", "nome": "Garen", "funcao": "Torre", "anims": {"idle": "Idle1_Base", "run": "Run_Spell1", "attack": "Crit", "death": "Death"}},
		"torre_2": {"caminho": "res://Modelos/galio.glb", "nome": "Galio", "funcao": "Torre", "anims": {"idle": "Idle2_Base", "run": "Run_Haste", "attack": "Attack_Passive", "death": "Death"}},
		"peao": {"caminho": "res://Modelos/krug.glb", "nome": "Krug", "funcao": "Peão", "anims": {"idle": "Krug_Idle_Normal", "run": "Run", "attack": "Attack3", "death": "Death"}},
		"cavalo_1": {"caminho": "res://Modelos/shyvana.glb", "nome": "Shyvana", "funcao": "Cavalo", "anims": {"idle": "IdleBase", "run": "Run_Haste", "attack": "Spell1_Attack2_start.Shyvana_Rework", "death": "Death"}},
		"cavalo_2": {"caminho": "res://Modelos/poppy.glb", "nome": "Poppy", "funcao": "Cavalo", "anims": {"idle": "Idle1_Base", "run": "Run_Homaguard", "attack": "Spell4_Instant", "death": "Death"}},
		"rei": {"caminho": "res://Modelos/jarvan_iv.glb", "nome": "Jarvan IV", "funcao": "Rei", "anims": {"idle": "Idle2", "run": "Run", "attack": "Spell1", "death": "Death"}}
	},
	"Noxus": {
		"bispo_1": {"caminho": "res://Modelos/ambessa.glb", "nome": "Ambessa", "funcao": "Bispo", "anims": {"idle": "IdleBase", "run": "RunFast", "attack": "Spell3", "death": "Death"}},
		"bispo_2": {"caminho": "res://Modelos/katarina.glb", "nome": "Katarina", "funcao": "Bispo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"rainha": {"caminho": "res://Modelos/leblanc.glb", "nome": "LeBlanc", "funcao": "Rainha", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"torre_1": {"caminho": "res://Modelos/darius.glb", "nome": "Darius", "funcao": "Torre", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"torre_2": {"caminho": "res://Modelos/sion.glb", "nome": "Sion", "funcao": "Torre", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"peao": {"caminho": "res://Modelos/cao.glb", "nome": "Cão", "funcao": "Peão", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"cavalo_1": {"caminho": "res://Modelos/rell.glb", "nome": "Rell", "funcao": "Cavalo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"cavalo_2": {"caminho": "res://Modelos/kled.glb", "nome": "Kled", "funcao": "Cavalo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"rei": {"caminho": "res://Modelos/swain.glb", "nome": "Swain", "funcao": "Rei", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}}
	},
	"Ionia": {
		"bispo_1": {"caminho": "res://Modelos/yone.glb", "nome": "Yone", "funcao": "Bispo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"bispo_2": {"caminho": "res://Modelos/yasuo.glb", "nome": "Yasuo", "funcao": "Bispo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"rainha": {"caminho": "res://Modelos/karma.glb", "nome": "Karma", "funcao": "Rainha", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"torre_1": {"caminho": "res://Modelos/sett.glb", "nome": "Sett", "funcao": "Torre", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"torre_2": {"caminho": "res://Modelos/lee_sin.glb", "nome": "Lee Sin", "funcao": "Torre", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"peao": {"caminho": "res://Modelos/espirito.glb", "nome": "Espírito", "funcao": "Peão", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"cavalo_1": {"caminho": "res://Modelos/zed.glb", "nome": "Zed", "funcao": "Cavalo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"cavalo_2": {"caminho": "res://Modelos/akali.glb", "nome": "Akali", "funcao": "Cavalo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"rei": {"caminho": "res://Modelos/shen.glb", "nome": "Shen", "funcao": "Rei", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}}
	},
	"Ilha das Sombras": {
		"bispo_1": {"caminho": "res://Modelos/karthus.glb", "nome": "Karthus", "funcao": "Bispo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"bispo_2": {"caminho": "res://Modelos/kalista.glb", "nome": "Kalista", "funcao": "Bispo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"rainha": {"caminho": "res://Modelos/gwen.glb", "nome": "Gwen", "funcao": "Rainha", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"torre_1": {"caminho": "res://Modelos/maokai.glb", "nome": "Maokai", "funcao": "Torre", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"torre_2": {"caminho": "res://Modelos/yorick.glb", "nome": "Yorick", "funcao": "Torre", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"peao": {"caminho": "res://Modelos/carnical.glb", "nome": "Carniçal", "funcao": "Peão", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"cavalo_1": {"caminho": "res://Modelos/hecarim.glb", "nome": "Hecarim", "funcao": "Cavalo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"cavalo_2": {"caminho": "res://Modelos/elise.glb", "nome": "Elise", "funcao": "Cavalo", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}},
		"rei": {"caminho": "res://Modelos/viego.glb", "nome": "Viego", "funcao": "Rei", "anims": {"idle": "Idle1", "run": "Run", "attack": "Attack1", "death": "Death"}}
	}
}

func _ready():
	montar_dicionario_partida()
	configurar_fundo()
	desenhar_tabuleiro_visual()
	posicionar_todas_as_pecas()

func montar_dicionario_partida():
	var f_b = GameManager.faccao_branca if GameManager else "Demacia"
	var f_p = GameManager.faccao_preta if GameManager else "Noxus"
	var brancas = banco_faccoes[f_b]
	var pretas = banco_faccoes[f_p]
	for chave in brancas.keys(): modelos_pecas[chave + "_b"] = brancas[chave]
	for chave in pretas.keys(): modelos_pecas[chave + "_p"] = pretas[chave]

func configurar_fundo():
	if imagem_fundo != null:
		var env = $WorldEnvironment.environment
		if env.sky == null: env.sky = Sky.new()
		var sky_mat = PanoramaSkyMaterial.new()
		sky_mat.panorama = imagem_fundo
		env.sky.sky_material = sky_mat
		env.background_mode = Environment.BG_SKY

func desenhar_tabuleiro_visual():
	for x in range(8):
		for z in range(8):
			var casa = StaticBody3D.new()
			casa.name = "Casa_" + str(x) + "_" + str(z)
			var mesh = MeshInstance3D.new()
			var box = BoxMesh.new()
			box.size = Vector3(TAMANHO_CASA, 0.2, TAMANHO_CASA)
			mesh.mesh = box
			mesh.position = Vector3(x * TAMANHO_CASA, -0.1, z * TAMANHO_CASA)
			var mat = StandardMaterial3D.new()
			if (x + z) % 2 == 0:
				mat.albedo_color = Color(0.2, 0.2, 0.2)
			else:
				mat.albedo_color = Color(0.9, 0.9, 0.9)
			mesh.material_override = mat
			casa.add_child(mesh)
			var col = CollisionShape3D.new()
			var shape = BoxShape3D.new()
			shape.size = Vector3(TAMANHO_CASA, 0.2, TAMANHO_CASA)
			col.shape = shape
			col.position = Vector3(x * TAMANHO_CASA, -0.1, z * TAMANHO_CASA)
			casa.add_child(col)
			add_child(casa)

func posicionar_todas_as_pecas():
	var layout = [
		["torre_1_b", "cavalo_1_b", "bispo_1_b", "rainha_b", "rei_b", "bispo_2_b", "cavalo_2_b", "torre_2_b"],
		["peao_b", "peao_b", "peao_b", "peao_b", "peao_b", "peao_b", "peao_b", "peao_b"],
		["", "", "", "", "", "", "", ""],
		["", "", "", "", "", "", "", ""],
		["", "", "", "", "", "", "", ""],
		["", "", "", "", "", "", "", ""],
		["peao_p", "peao_p", "peao_p", "peao_p", "peao_p", "peao_p", "peao_p", "peao_p"],
		["torre_1_p", "cavalo_1_p", "bispo_1_p", "rainha_p", "rei_p", "bispo_2_p", "cavalo_2_p", "torre_2_p"]
	]
	for z in range(8):
		for x in range(8):
			var tipo = layout[z][x]
			if tipo != "":
				criar_peca(tipo, Vector2(x, z))

func criar_peca(tipo: String, pos_matriz: Vector2) -> void:
	var dados: Dictionary = modelos_pecas[tipo]
	var caminho_configurado: String = String(dados.get("caminho", ""))

	var PecaScript = preload("res://Peca.gd")
	var nova_peca := PecaScript.new() as Peca
	nova_peca.name = String(dados.get("nome", tipo))

	var time := "b" if tipo.ends_with("_b") else "p"
	nova_peca.cor_time = time
	nova_peca.funcao = String(dados.get("funcao", ""))

	var instancia_modelo: Node = null
	var caminho_real := localizar_modelo(caminho_configurado)

	if caminho_real != "":
		var recurso_modelo: Resource = load(caminho_real)
		if recurso_modelo is PackedScene:
			instancia_modelo = (recurso_modelo as PackedScene).instantiate()
			nova_peca.add_child(instancia_modelo)
			print("[League Chess] GLB carregado: %s -> %s" % [nova_peca.name, caminho_real])
		else:
			push_warning("[League Chess] O arquivo existe, mas não é uma PackedScene: %s" % caminho_real)
	else:
		push_warning("[League Chess] GLB não encontrado para %s. Caminho configurado: %s" % [nova_peca.name, caminho_configurado])
		var fallback := CSGCylinder3D.new()
		fallback.name = "ModeloTemporario"
		nova_peca.add_child(fallback)

	var area := Area3D.new()
	var col := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(1.5, 3.0, 1.5)
	col.shape = shape
	col.position.y = 1.5
	area.add_child(col)
	nova_peca.add_child(area)

	var txt_legenda := "%s - %s (%s)" % [
		String(dados.get("nome", tipo)),
		String(dados.get("funcao", "")),
		"Brancas" if time == "b" else "Pretas"
	]
	area.mouse_entered.connect(func(): mostrar_legenda(txt_legenda))
	area.mouse_exited.connect(ocultar_legenda)

	add_child(nova_peca)
	nova_peca.global_position = obter_posicao_3d(pos_matriz)
	matriz[pos_matriz] = nova_peca

	if time == "p":
		nova_peca.rotation_degrees.y = 180.0

	# Inicializa o AnimationPlayer somente depois que a peça está na árvore.
	# Assim conseguimos definir o root_node para a raiz correta do GLB.
	if instancia_modelo != null:
		nova_peca.inicializar_animacoes(
			dados.get("anims", {}),
			time,
			instancia_modelo,
			String(dados.get("nome", tipo))
		)


func localizar_modelo(caminho_configurado: String) -> String:
	if caminho_configurado == "":
		return ""

	if ResourceLoader.exists(caminho_configurado):
		return caminho_configurado

	var nome_base := caminho_configurado.get_file().get_basename()
	var nome_normalizado := normalizar_nome_arquivo(nome_base)
	var diretorios := [
		"res://Modelos",
		"res://modelos",
		"res://assets/glb",
		"res://assets/GLB",
		"res://league_chess/assets/glb",
		"res://league_chess/assets/GLB",
		"res://league_chess/Modelos"
	]

	for diretorio in diretorios:
		var encontrado := buscar_glb_recursivo(diretorio, nome_normalizado)
		if encontrado != "":
			return encontrado

	return ""


func buscar_glb_recursivo(diretorio: String, nome_normalizado: String) -> String:
	var dir := DirAccess.open(diretorio)
	if dir == null:
		return ""

	dir.list_dir_begin()
	var arquivo := dir.get_next()

	while arquivo != "":
		if arquivo != "." and arquivo != "..":
			var caminho := diretorio.path_join(arquivo)

			if dir.current_is_dir():
				var encontrado := buscar_glb_recursivo(caminho, nome_normalizado)
				if encontrado != "":
					dir.list_dir_end()
					return encontrado
			elif arquivo.get_extension().to_lower() == "glb":
				var nome_arquivo := arquivo.get_basename()
				if normalizar_nome_arquivo(nome_arquivo) == nome_normalizado:
					dir.list_dir_end()
					return caminho

		arquivo = dir.get_next()

	dir.list_dir_end()
	return ""


func normalizar_nome_arquivo(texto: String) -> String:
	var resultado := texto.to_lower().strip_edges()
	var substituicoes := {
		"á": "a", "à": "a", "ã": "a", "â": "a",
		"é": "e", "ê": "e",
		"í": "i",
		"ó": "o", "ô": "o", "õ": "o",
		"ú": "u",
		"ç": "c"
	}
	for original in substituicoes:
		resultado = resultado.replace(original, substituicoes[original])

	for separador in [" ", "_", "-", ".", "'", "’", "(", ")", "[", "]"]:
		resultado = resultado.replace(separador, "")

	return resultado

func movimento_valido(peca: Peca, de_pos: Vector2, para_pos: Vector2) -> bool:
	var dx = para_pos.x - de_pos.x
	var dz = para_pos.y - de_pos.y
	var abs_dx = abs(dx)
	var abs_dz = abs(dz)
	
	var direcao_frente = 1 if peca.cor_time == "b" else -1
	
	match peca.funcao:
		"Peão":
			if dx == 0 and dz == direcao_frente and not matriz.has(para_pos): return true
			var pos_inicial = 1 if peca.cor_time == "b" else 6
			if dx == 0 and dz == 2 * direcao_frente and de_pos.y == pos_inicial and not matriz.has(para_pos) and not matriz.has(de_pos + Vector2(0, direcao_frente)):
				return true
			if abs_dx == 1 and dz == direcao_frente and matriz.has(para_pos) and matriz[para_pos].cor_time != peca.cor_time:
				return true
			return false
		"Torre":
			if dx != 0 and dz != 0: return false
			return caminho_livre(de_pos, para_pos)
		"Cavalo":
			if (abs_dx == 2 and abs_dz == 1) or (abs_dx == 1 and abs_dz == 2): return true
			return false
		"Bispo":
			if abs_dx != abs_dz: return false
			return caminho_livre(de_pos, para_pos)
		"Rainha":
			if dx != 0 and dz != 0 and abs_dx != abs_dz: return false
			return caminho_livre(de_pos, para_pos)
		"Rei":
			if abs_dx <= 1 and abs_dz <= 1: return true
			return false
	return false

func caminho_livre(de_pos: Vector2, para_pos: Vector2) -> bool:
	var dx = sign(para_pos.x - de_pos.x)
	var dz = sign(para_pos.y - de_pos.y)
	var pos_atual = de_pos + Vector2(dx, dz)
	
	while pos_atual != para_pos:
		if matriz.has(pos_atual):
			return false 
		pos_atual += Vector2(dx, dz)
	return true

func _input(event):
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		var camera = get_viewport().get_camera_3d()
		if not camera: return
		var mouse_pos = get_viewport().get_mouse_position()
		var origem = camera.project_ray_origin(mouse_pos)
		var direcao = camera.project_ray_normal(mouse_pos)
		
		if direcao.y != 0:
			var t = -origem.y / direcao.y
			var ponto = origem + direcao * t
			var x_matriz = round(ponto.x / TAMANHO_CASA)
			var z_matriz = round(ponto.z / TAMANHO_CASA)
			
			if x_matriz >= 0 and x_matriz < 8 and z_matriz >= 0 and z_matriz < 8:
				clicar_casa(Vector2(x_matriz, z_matriz))

func clicar_casa(pos: Vector2):
	if matriz.has(pos):
		var peca_clicada = matriz[pos]
		if peca_clicada.cor_time == turno_atual:
			peca_selecionada = peca_clicada
			pos_selecionada = pos
		elif peca_selecionada != null:
			if movimento_valido(peca_selecionada, pos_selecionada, pos):
				solicitar_movimento(pos_selecionada, pos)
				peca_selecionada = null
				turno_atual = "p" if turno_atual == "b" else "b"
	elif peca_selecionada != null:
		if movimento_valido(peca_selecionada, pos_selecionada, pos):
			solicitar_movimento(pos_selecionada, pos)
			peca_selecionada = null
			turno_atual = "p" if turno_atual == "b" else "b"

func mostrar_legenda(texto: String):
	if has_node("UI/Tooltip"):
		get_node("UI/Tooltip").text = texto
		get_node("UI/Tooltip").visible = true

func ocultar_legenda():
	if has_node("UI/Tooltip"):
		get_node("UI/Tooltip").visible = false

func _process(_delta):
	if has_node("UI/Tooltip") and get_node("UI/Tooltip").visible:
		get_node("UI/Tooltip").position = get_viewport().get_mouse_position() + Vector2(20, -20)

func obter_posicao_3d(posicao_matriz: Vector2) -> Vector3:
	return Vector3(posicao_matriz.x * TAMANHO_CASA, 0, posicao_matriz.y * TAMANHO_CASA)

func solicitar_movimento(de_pos: Vector2, para_pos: Vector2):
	if not matriz.has(de_pos): return 
	var peca = matriz[de_pos]
	var posicao_alvo_3d = obter_posicao_3d(para_pos)
	var tem_alvo = matriz.has(para_pos)
	var caminho_alvo = ""
	if tem_alvo:
		caminho_alvo = matriz[para_pos].get_path()
		
	# Corrige problema de travamento no Modo Local/Treino quando nao ha peer RPC
	var pode_chamar_rpc = false
	if multiplayer.multiplayer_peer:
		if multiplayer.multiplayer_peer.get_connection_status() != MultiplayerPeer.CONNECTION_DISCONNECTED:
			pode_chamar_rpc = true
			
	if pode_chamar_rpc:
		peca.rpc("mover_e_atacar", posicao_alvo_3d, tem_alvo, caminho_alvo)
	else:
		peca.mover_e_atacar(posicao_alvo_3d, tem_alvo, caminho_alvo)
		
	matriz[para_pos] = peca
	matriz.erase(de_pos)
