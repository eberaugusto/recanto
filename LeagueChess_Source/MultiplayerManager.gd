extends Node
const PORTA = 8080
var peer = ENetMultiplayerPeer.new()
func criar_host():
    var erro = peer.create_server(PORTA)
    if erro == OK: multiplayer.multiplayer_peer = peer
func conectar_cliente(ip_radmin: String):
    var erro = peer.create_client(ip_radmin, PORTA)
    if erro == OK: multiplayer.multiplayer_peer = peer
