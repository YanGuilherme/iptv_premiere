.PHONY: help build up down restart logs ps playlist channels health live

PORT ?= 8000
COMPOSE ?= docker compose

help:
	@echo "Targets:"
	@echo "  make build      Build da imagem Docker"
	@echo "  make up         Sobe a API em background"
	@echo "  make down       Para e remove o container"
	@echo "  make restart    Reinicia o serviço"
	@echo "  make logs       Acompanha os logs da API"
	@echo "  make ps         Status dos containers"
	@echo "  make health     GET /health"
	@echo "  make channels   GET /channels (JSON)"
	@echo "  make playlist   GET /playlist.m3u"
	@echo "  make live ID=premiere-esportes-1"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart api

logs:
	$(COMPOSE) logs -f api

ps:
	$(COMPOSE) ps

health:
	curl -fsS "http://localhost:$(PORT)/health"

channels:
	curl -fsS "http://localhost:$(PORT)/channels"

playlist:
	curl -fsS "http://localhost:$(PORT)/playlist.m3u"

ID ?= premiere-esportes-1
live:
	curl -fsS "http://localhost:$(PORT)/live/$(ID)"
