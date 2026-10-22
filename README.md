# Recanto v1.0 — Preparado para hospedagem HTTPS e PWA

Base: Recanto v0.9.2, mantendo Perfil, Cards, Inventário, Pet, Loja, Missões, trocas, coleções, selos, jogos favoritos, administração pelo Discord ID e assets.

## Comece por estes guias

- **`HOSPEDAR_RECANTO_PASSO_A_PASSO.md`** — instalar na internet pela primeira vez, usando GitHub + Render + Neon + Cloudinary opcional.
- **`COMO_ATUALIZAR_SEM_REINSTALAR.md`** — enviar novas versões e ativar o aviso **Atualizar** dentro do PWA.
- **`CONFIGURAR_DISCORD.md`** — detalhes do OAuth2 Discord; para a hospedagem use Redirect URI HTTPS (não localhost).
- **`ASSETS_GUIA.md`** — personalização de imagens e ícones.

## Mudanças da v1.0

- Modo de produção exige `DATABASE_URL` PostgreSQL persistente, `PUBLIC_BASE_URL` HTTPS e login Discord configurado.
- Upload de imagens para Cloudinary (quando credenciais configuradas). Não utiliza disco efêmero do Render para guardar imagens enviadas.
- PWA oferece **banner de nova versão** e a opção **Configurações → Verificar atualizações**. Ao atualizar, preserva sessão e dados do banco.
- `render.yaml` pronto para Render e health check `/api/health`.
- Todos os recursos e sistemas da v0.9.2 continuam na base.

## Teste local no PC (opcional)

Use Python 3.12. Execute `INSTALAR.bat` e `INICIAR_RECANTO.bat`, depois abra `http://localhost:5173`. Para login local, preencha `backend/.env` conforme `CONFIGURAR_DISCORD.md`.

## Cuidados antes de compartilhar com sua comunidade

- **Não publicar** `backend/.env`, `backend/recanto.db`, tokens ou senhas em GitHub ou capturas de tela.
- Não usar o arquivo SQLite local no Render Free. PostgreSQL Neon obrigatório.
- O banco Neon começa sem os dados de progresso do PC. Uma migração não é automática.
- Modelos 3D gravados apenas no PC precisam ser publicados em URL persistente ou adicionados ao repositório.
- Render Free pode adormecer e demorar na primeira abertura após inatividade.
- A versão está **preparada para publicação**, mas ainda precisa ser configurada e testada com suas contas reais no Render/Discord/Neon.
