extends Node3D
class_name Peca

signal movimento_concluido
signal morte_concluida

var animation_player: AnimationPlayer
var anims_custom: Dictionary = {}
var animacoes_resolvidas: Dictionary = {}
var cor_time: String = "b"
var funcao: String = ""
var nome_personagem: String = ""
var animacao_atual_loop: StringName = &""


# Inicializa o AnimationPlayer do GLB depois que a peça entrou na árvore.
# A raiz das trilhas é descoberta pelos caminhos reais dos tracks, em vez de
# presumir que o AnimationPlayer sempre está diretamente sob a raiz do GLB.
func inicializar_animacoes(
	dicionario_animacoes: Dictionary,
	time: String,
	raiz_modelo: Node = null,
	nome: String = ""
) -> void:
	anims_custom = dicionario_animacoes.duplicate(true)
	cor_time = time
	nome_personagem = nome

	if raiz_modelo == null or not is_instance_valid(raiz_modelo):
		push_warning("[League Chess][ANIMAÇÕES] %s: raiz do GLB inválida." % nome_personagem)
		return

	var players: Array[AnimationPlayer] = []
	_coletar_animation_players(raiz_modelo, players)
	if players.is_empty():
		push_warning("[League Chess][ANIMAÇÕES] %s: nenhum AnimationPlayer encontrado." % nome_personagem)
		return

	# Escolhe o player e a raiz que realmente alcançam mais trilhas do esqueleto.
	var melhor_player: AnimationPlayer = null
	var melhor_raiz: Node = null
	var melhor_pontuacao := -1
	var melhor_desempate := -1
	var melhor_total := 0
	var melhor_resolvidas := 0

	for candidato in players:
		animation_player = candidato
		_resolver_todas_animacoes()
		var resultado: Dictionary = _encontrar_melhor_raiz(candidato, raiz_modelo)
		var pontuacao := int(resultado.get("pontuacao", 0))
		var desempate := candidato.get_animation_list().size()
		if pontuacao > melhor_pontuacao or (pontuacao == melhor_pontuacao and desempate > melhor_desempate):
			melhor_player = candidato
			melhor_raiz = resultado.get("raiz") as Node
			melhor_pontuacao = pontuacao
			melhor_desempate = desempate
			melhor_total = int(resultado.get("total", 0))
			melhor_resolvidas = int(resultado.get("resolvidas", 0))

	animation_player = melhor_player
	if animation_player == null:
		push_warning("[League Chess][ANIMAÇÕES] %s: não foi possível selecionar AnimationPlayer." % nome_personagem)
		return

	_resolver_todas_animacoes()
	if melhor_raiz != null and melhor_pontuacao > 0:
		animation_player.root_node = animation_player.get_path_to(melhor_raiz)
	else:
		# Se nenhum caminho de trilha pôde ser validado, não destrói a
		# configuração original importada do GLB.
		push_warning(
			"[League Chess][ROOT] %s: não foi possível validar os caminhos das animações. Root original mantido: %s"
			% [nome_personagem, str(animation_player.root_node)]
		)

	animation_player.active = true
	animation_player.speed_scale = 1.0
	animation_player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_IDLE
	if not animation_player.animation_finished.is_connected(_on_animation_finished):
		animation_player.animation_finished.connect(_on_animation_finished)

	_forcar_esqueletos_animaveis(raiz_modelo)
	_imprimir_diagnostico_animacoes(melhor_resolvidas, melhor_total)

	# Aguarda um frame para o GLB terminar de entrar na árvore e então aplica
	# a primeira pose da animação. Isso evita deixar o esqueleto na pose T.
	call_deferred("_iniciar_idle_apos_frame")


func _coletar_animation_players(no: Node, resultado: Array[AnimationPlayer]) -> void:
	if no is AnimationPlayer:
		resultado.append(no as AnimationPlayer)
	for filho in no.get_children():
		_coletar_animation_players(filho, resultado)


func _adicionar_raiz(lista: Array[Node], no: Node) -> void:
	if no != null and is_instance_valid(no) and not lista.has(no):
		lista.append(no)


func _encontrar_melhor_raiz(player: AnimationPlayer, raiz_modelo: Node) -> Dictionary:
	var candidatos: Array[Node] = []

	# Primeiro testa a raiz que veio do importador do GLB.
	if not player.root_node.is_empty():
		_adicionar_raiz(candidatos, player.get_node_or_null(player.root_node))

	# Depois testa o pai imediato, a raiz instanciada do GLB e os ancestrais.
	var atual: Node = player.get_parent()
	while atual != null:
		_adicionar_raiz(candidatos, atual)
		atual = atual.get_parent()
	_adicionar_raiz(candidatos, raiz_modelo)

	var melhor: Node = null
	var melhor_pontuacao := -1
	var melhor_total := 0
	var melhor_resolvidas := 0

	for raiz_candidata in candidatos:
		var dados := _pontuar_raiz(player, raiz_candidata)
		var pontuacao := int(dados.get("pontuacao", 0))
		if pontuacao > melhor_pontuacao:
			melhor = raiz_candidata
			melhor_pontuacao = pontuacao
			melhor_total = int(dados.get("total", 0))
			melhor_resolvidas = int(dados.get("resolvidas", 0))

	return {
		"raiz": melhor,
		"pontuacao": max(0, melhor_pontuacao),
		"total": melhor_total,
		"resolvidas": melhor_resolvidas
	}


func _pontuar_raiz(player: AnimationPlayer, raiz: Node) -> Dictionary:
	var pontuacao := 0
	var total := 0
	var resolvidas := 0
	var idle_escolhido := String(animacoes_resolvidas.get("idle", ""))
	var run_escolhido := String(animacoes_resolvidas.get("run", ""))

	for nome_animacao in player.get_animation_list():
		var animacao: Animation = player.get_animation(nome_animacao)
		if animacao == null:
			continue

		var nome := String(nome_animacao)
		var peso := 1
		if nome == idle_escolhido:
			peso = 8
		elif nome == run_escolhido:
			peso = 3

		for indice in range(animacao.get_track_count()):
			var caminho_trilha: NodePath = animacao.track_get_path(indice)
			var caminho_no := _caminho_no_da_trilha(caminho_trilha)
			if caminho_no.is_empty():
				continue
			total += 1
			var alvo := raiz.get_node_or_null(caminho_no)
			if alvo == null:
				continue

			resolvidas += 1
			pontuacao += peso

			# Trilhas de osso usam o nome do osso como subnome do Skeleton3D.
			if alvo is Skeleton3D and caminho_trilha.get_subname_count() > 0:
				var nome_osso := String(caminho_trilha.get_subname(0))
				if (alvo as Skeleton3D).find_bone(nome_osso) >= 0:
					pontuacao += peso * 5

	return {"pontuacao": pontuacao, "total": total, "resolvidas": resolvidas}


func _caminho_no_da_trilha(caminho_trilha: NodePath) -> NodePath:
	var nomes := PackedStringArray()
	for indice in range(caminho_trilha.get_name_count()):
		nomes.append(String(caminho_trilha.get_name(indice)))
	if nomes.is_empty():
		return NodePath(".")
	return NodePath("/".join(nomes))


func _forcar_esqueletos_animaveis(no: Node) -> void:
	if no is Skeleton3D:
		(no as Skeleton3D).show_rest_only = false
	for filho in no.get_children():
		_forcar_esqueletos_animaveis(filho)


func _normalizar_nome(texto: String) -> String:
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
	for separador in [" ", "_", "-", ".", "/", "\\", ":", "'", "’", "(", ")", "[", "]"]:
		resultado = resultado.replace(separador, "")
	return resultado


func _resolver_todas_animacoes() -> void:
	animacoes_resolvidas.clear()
	for chave in ["idle", "run", "attack", "death"]:
		var nome_resolvido := _resolver_animacao(chave)
		if nome_resolvido != &"":
			animacoes_resolvidas[chave] = nome_resolvido
	if not animacoes_resolvidas.has("run") and animacoes_resolvidas.has("idle"):
		animacoes_resolvidas["run"] = animacoes_resolvidas["idle"]


func _resolver_animacao(chave: String) -> StringName:
	if animation_player == null:
		return &""
	var lista := animation_player.get_animation_list()
	if lista.is_empty():
		return &""

	var solicitada := String(anims_custom.get(chave, "")).strip_edges()
	var solicitada_normalizada := _normalizar_nome(solicitada)

	# Correspondência exata tem prioridade absoluta.
	if solicitada_normalizada != "":
		for nome_animacao in lista:
			if _normalizar_nome(String(nome_animacao)) == solicitada_normalizada:
				return nome_animacao

	# Nomes específicos do personagem podem ser sufixados pelo exportador
	# (por exemplo, Krug_Idle_Normal_anm). Não usa busca parcial para nomes
	# genéricos como apenas "Idle" ou "Run", pois isso selecionava transições.
	if solicitada_normalizada.length() >= 5:
		var melhor_nome: StringName = &""
		var melhor_diferenca := 999999
		for nome_animacao in lista:
			var nome_normalizado := _normalizar_nome(String(nome_animacao))
			if nome_normalizado.contains(solicitada_normalizada):
				var diferenca := absi(nome_normalizado.length() - solicitada_normalizada.length())
				if diferenca < melhor_diferenca and not _eh_transicao(String(nome_animacao), chave):
					melhor_diferenca = diferenca
					melhor_nome = nome_animacao
		if melhor_nome != &"":
			return melhor_nome

	var melhor_nome_categoria: StringName = &""
	var melhor_pontuacao := -1.0
	for nome_animacao in lista:
		var pontuacao := _pontuar_por_categoria(String(nome_animacao), chave)
		if pontuacao > melhor_pontuacao:
			melhor_pontuacao = pontuacao
			melhor_nome_categoria = nome_animacao
	if melhor_pontuacao > 0.0:
		return melhor_nome_categoria

	if chave == "idle":
		for nome_animacao in lista:
			var nome_normalizado := _normalizar_nome(String(nome_animacao))
			if nome_normalizado not in ["reset", "bindpose", "rest"]:
				return nome_animacao
	return &""


func _eh_transicao(nome_animacao: String, chave: String) -> bool:
	var nome := _normalizar_nome(nome_animacao)
	if chave == "idle":
		return _contem_algum(nome, ["toidle", "intoidle", "idleto", "idlein", "idleout", "transition", "intro", "winddown"])
	if chave == "run":
		return _contem_algum(nome, ["torun", "intorun", "runin", "runout", "transition", "critto", "attackto"])
	if chave == "attack":
		return _contem_algum(nome, ["toidle", "torun", "intoidle", "intorun", "transition"])
	return false


func _pontuar_por_categoria(nome_animacao: String, chave: String) -> float:
	var nome := _normalizar_nome(nome_animacao)
	var transicao := _eh_transicao(nome_animacao, chave)
	match chave:
		"idle":
			if not transicao and _contem_algum(nome, ["idle", "stand", "breath", "wait"]):
				return 1200.0 - float(nome.length()) * 0.01
			if not transicao and _contem_algum(nome, ["base", "default", "neutral"]):
				if _contem_algum(nome, ["run", "walk", "attack", "spell", "death", "die", "recall", "dance", "taunt"]):
					return -1.0
				return 500.0 - float(nome.length()) * 0.01
		"run":
			if not transicao and _contem_algum(nome, ["runfast", "runhaste", "runbase", "runnormal", "runslow", "runhomeguard"]):
				return 1300.0 - float(nome.length()) * 0.01
			if not transicao and nome.contains("run"):
				return 1100.0 - float(nome.length()) * 0.01
			if nome.contains("walk"):
				return 1000.0 - float(nome.length()) * 0.01
			if nome.contains("locomotion"):
				return 900.0 - float(nome.length()) * 0.01
			if not transicao and _contem_algum(nome, ["sprint", "jog", "move"]):
				return 800.0 - float(nome.length()) * 0.01
		"attack":
			if not transicao and nome.contains("attack"):
				return 1200.0 - float(nome.length()) * 0.01
			if not transicao and nome.contains("crit"):
				return 1100.0 - float(nome.length()) * 0.01
			if not transicao and nome.contains("spell"):
				return 1000.0 - float(nome.length()) * 0.01
			if not transicao and nome.contains("cast"):
				return 900.0 - float(nome.length()) * 0.01
			if not transicao and _contem_algum(nome, ["combo", "combat", "basicattack", "hit"]):
				return 750.0 - float(nome.length()) * 0.01
		"death":
			if nome.contains("death"):
				return 1200.0 - float(nome.length()) * 0.01
			if nome.contains("dead") or nome.contains("die"):
				return 1000.0 - float(nome.length()) * 0.01
			if nome.contains("defeat"):
				return 800.0 - float(nome.length()) * 0.01
			if nome.contains("knockout"):
				return 700.0 - float(nome.length()) * 0.01
	return -1.0


func _contem_algum(texto: String, termos: Array) -> bool:
	for termo in termos:
		if texto.contains(String(termo)):
			return true
	return false


func _contar_trilhas_validas(nome_animacao: StringName) -> Dictionary:
	if animation_player == null:
		return {"validas": 0, "total": 0}
	var raiz := animation_player.get_node_or_null(animation_player.root_node)
	if raiz == null:
		return {"validas": 0, "total": 0}
	var animacao: Animation = animation_player.get_animation(nome_animacao)
	if animacao == null:
		return {"validas": 0, "total": 0}
	var validas := 0
	var total := 0
	for indice in range(animacao.get_track_count()):
		var caminho := _caminho_no_da_trilha(animacao.track_get_path(indice))
		if caminho.is_empty():
			continue
		total += 1
		if raiz.get_node_or_null(caminho) != null:
			validas += 1
	return {"validas": validas, "total": total}


func _imprimir_diagnostico_animacoes(resolvidas: int, total: int) -> void:
	var idle: StringName = animacoes_resolvidas.get("idle", &"")
	var cobertura := _contar_trilhas_validas(idle)
	print(
		"[League Chess][ANIMAÇÕES] %s | Player: %s | Root: %s | Idle: %s | Run: %s | Attack: %s | Death: %s | Trilhas: %d/%d | Raiz validada: %d/%d"
		% [
			nome_personagem,
			str(animation_player.get_path()),
			str(animation_player.root_node),
			String(idle) if idle != &"" else "NÃO ENCONTRADA",
			String(animacoes_resolvidas.get("run", &"")),
			String(animacoes_resolvidas.get("attack", &"")),
			String(animacoes_resolvidas.get("death", &"")),
			int(cobertura.get("validas", 0)),
			int(cobertura.get("total", 0)),
			resolvidas,
			total
		]
	)


func _iniciar_idle_apos_frame() -> void:
	await get_tree().process_frame
	if not is_inside_tree() or animation_player == null or not is_instance_valid(animation_player):
		return
	animation_player.active = true
	animation_player.speed_scale = 1.0
	animation_player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_IDLE
	tocar_animacao("idle", true)
	animation_player.advance(0.0)
	print(
		"[League Chess][PLAY] %s | atual=%s | tocando=%s | root=%s"
		% [nome_personagem, String(animation_player.current_animation), str(animation_player.is_playing()), str(animation_player.root_node)]
	)
	if not animation_player.is_playing():
		push_warning("[League Chess][PLAY] %s: o AnimationPlayer não iniciou a animação Idle." % nome_personagem)


func tocar_animacao(chave: String, em_loop: bool = false) -> float:
	if animation_player == null or not is_instance_valid(animation_player):
		return 0.0
	var nome_exato: StringName = animacoes_resolvidas.get(chave, &"")
	if nome_exato == &"":
		push_warning("[League Chess] %s: animação '%s' não foi resolvida." % [nome_personagem, chave])
		return 0.0

	animacao_atual_loop = nome_exato if em_loop else &""
	animation_player.active = true
	animation_player.speed_scale = 1.0
	animation_player.callback_mode_process = AnimationMixer.ANIMATION_CALLBACK_MODE_PROCESS_IDLE
	if animation_player.current_animation != nome_exato or not animation_player.is_playing():
		animation_player.play(nome_exato, -1.0, 1.0, false)
	return animation_player.current_animation_length


func _on_animation_finished(anim_name: StringName) -> void:
	if anim_name == animacao_atual_loop and animation_player != null and is_instance_valid(animation_player):
		animation_player.play(anim_name, -1.0, 1.0, false)


@rpc("any_peer", "call_local")
func mover_e_atacar(posicao_alvo_3d: Vector3, tem_alvo: bool, caminho_alvo: NodePath = NodePath("")) -> void:
	var direcao_movimento := posicao_alvo_3d - global_position
	if direcao_movimento.length() > 0.01:
		look_at(Vector3(posicao_alvo_3d.x, global_position.y, posicao_alvo_3d.z), Vector3.UP)
		rotate_object_local(Vector3.UP, PI)

	tocar_animacao("run", true)
	var posicao_parada := posicao_alvo_3d
	if tem_alvo:
		var direcao := direcao_movimento.normalized()
		posicao_parada = posicao_alvo_3d - (direcao * 1.5)

	var tempo_corrida := maxf(0.4, global_position.distance_to(posicao_parada) / 5.0)
	var tween := create_tween()
	tween.tween_property(self, "global_position", posicao_parada, tempo_corrida)
	await tween.finished

	if tem_alvo and not caminho_alvo.is_empty():
		var peca_alvo := get_node_or_null(caminho_alvo)
		if peca_alvo != null:
			look_at(Vector3(peca_alvo.global_position.x, global_position.y, peca_alvo.global_position.z), Vector3.UP)
			rotate_object_local(Vector3.UP, PI)
			var tempo_ataque := tocar_animacao("attack", false)
			if tempo_ataque > 0.0:
				await get_tree().create_timer(tempo_ataque).timeout
			else:
				await get_tree().create_timer(0.5).timeout
			if peca_alvo is Peca:
				var alvo_peca := peca_alvo as Peca
				alvo_peca.sofrer_morte()
				await alvo_peca.morte_concluida
			look_at(Vector3(posicao_alvo_3d.x, global_position.y, posicao_alvo_3d.z), Vector3.UP)
			rotate_object_local(Vector3.UP, PI)
			tocar_animacao("run", true)
			var tween2 := create_tween()
			tween2.tween_property(self, "global_position", posicao_alvo_3d, 0.4)
			await tween2.finished

	rotation.y = 0.0 if cor_time == "b" else PI
	tocar_animacao("idle", true)
	movimento_concluido.emit()


func sofrer_morte() -> void:
	var tempo_morte := tocar_animacao("death", false)
	if tempo_morte > 0.0:
		await get_tree().create_timer(tempo_morte).timeout
	morte_concluida.emit()
	queue_free()
