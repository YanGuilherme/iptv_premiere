# IPTV Premiere

API em FastAPI que publica uma playlist M3U e funciona como proxy para streams
HLS. O proxy busca playlists e segmentos na origem, injeta os headers definidos
para cada canal e reescreve os endereços da playlist para passarem pela própria
API.

## Como funciona

1. Os canais são carregados de `app/channels.json` quando a aplicação inicia.
2. `/playlist.m3u` gera uma playlist M3U com um endereço `/live/{tvg_id}.m3u8`
   para cada canal.
3. Quando um player solicita `/live/{tvg_id}.m3u8`, a API busca a playlist na
   origem usando a URL e os headers daquele canal.
4. A API reescreve URLs de segmentos e playlists aninhadas para `/proxy/{tvg_id}`,
   mantendo a origem atrás do proxy.
5. Cada pedido ao proxy é encaminhado à origem. Segmentos são transmitidos sem
   carregar o arquivo inteiro na memória; playlists são lidas e reescritas antes
   de serem devolvidas.

As playlists reescritas recebem `Cache-Control: no-store`. O cliente HTTP mantém
conexões keep-alive por até 30 segundos, com timeout de 10 segundos para conexão
e timeout padrão de 60 segundos para leitura, escrita e aquisição de conexão.
Pedidos `HEAD` são enviados como `HEAD` à origem e não leem o corpo da resposta.

## Requisitos

- Python 3.12 ou superior
- Docker com Docker Compose (opcional, para executar em container)

## Configuração dos canais

Edite `app/channels.json`. O arquivo deve conter uma lista JSON; cada item
representa um canal:

```json
[
  {
    "tvg_id": "ESPN",
    "name": "ESPN",
    "group": "Esportes",
    "logo": "https://example.com/logo.png",
    "url": "https://origin.example/live/index.m3u8",
    "headers": {
      "User-Agent": "Player/1.0",
      "Referer": "https://origin.example/"
    }
  }
]
```

Campos:

| Campo | Descrição |
| --- | --- |
| `tvg_id` | Identificador único usado nas rotas da API. |
| `name` | Nome exibido na playlist. |
| `group` | Grupo exibido na playlist. |
| `logo` | URL do logotipo. |
| `url` | URL HTTP ou HTTPS da playlist de origem. |
| `headers` | Headers adicionais enviados à origem para buscar playlists e segmentos. |

`tvg_id` precisa ser único. `app/channels_rasc.json` é apenas um arquivo de
referência; a configuração carregada pela aplicação é `app/channels.json`.
Depois de alterar a configuração, reinicie a aplicação para carregar os canais
novamente.

## Executar com Docker Compose

Na raiz do repositório:

```bash
docker compose up -d --build
```

A API ficará disponível em `http://localhost:8000`. Para escolher outra porta
no host:

```bash
PORT=8080 docker compose up -d --build
```

Comandos úteis:

```bash
docker compose ps
docker compose logs -f api
docker compose restart api
docker compose down
```

O `Makefile` também oferece atalhos, por exemplo `make up`, `make health`,
`make channels`, `make playlist`, `make logs` e `make down`. Para consultar um
canal específico com o atalho, informe o identificador configurado:

```bash
make live ID=ESPN
```

O Compose monta `app/channels.json` no container como somente leitura. Após
editar esse arquivo, reinicie o serviço para carregar as alterações:

```bash
docker compose restart api
```

## Executar localmente

Crie um ambiente virtual, instale as dependências e inicie o servidor:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No Windows PowerShell, ative o ambiente virtual com:

```powershell
.venv\Scripts\Activate.ps1
```

Para usar outra porta na execução local, substitua `8000` no comando do Uvicorn.

## Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Informações básicas e rotas principais. |
| `GET` | `/health` | Verificação de saúde; retorna `{"status":"ok"}`. |
| `GET` | `/channels` | Lista os canais configurados. |
| `GET` | `/playlist.m3u` | Gera uma playlist M3U com todos os canais. |
| `GET`, `HEAD` | `/live/{tvg_id}` | Busca e reescreve a playlist do canal. |
| `GET`, `HEAD` | `/live/{tvg_id}.m3u8` | Mesmo acesso à playlist, com extensão explícita. |
| `GET`, `HEAD` | `/proxy/{tvg_id}?u={url}` | Busca um recurso HTTP/HTTPS através do proxy. |

O FastAPI também disponibiliza a documentação interativa em `/docs` e o schema
OpenAPI em `/openapi.json`.

Exemplos, considerando um canal com `tvg_id` igual a `ESPN`:

```bash
curl -i http://localhost:8000/health
curl -i http://localhost:8000/channels
curl -i http://localhost:8000/playlist.m3u
curl -i http://localhost:8000/live/ESPN.m3u8
curl -I http://localhost:8000/live/ESPN.m3u8
```

O player pode usar `http://<endereco-do-servidor>:8000/playlist.m3u` como
playlist. Se for acessar de outro dispositivo na rede, use o endereço IP do
servidor no lugar de `localhost`.

## Logs

Os logs da aplicação registram entregas de playlists, segmentos e outros
recursos, incluindo canal, nome do recurso, status HTTP, bytes e duração.
Também registram falhas da origem, erros de transmissão e pedidos interrompidos.
URLs completas, query strings e headers recebidos do cliente não são incluídos
nesses logs. O log INFO das requisições internas do `httpx` está desativado para
reduzir ruído.

Para acompanhar os logs no Docker:

```bash
docker compose logs -f api
```

## Desempenho

As playlists são lidas na memória para que seus endereços possam ser reescritos;
segmentos e outros recursos de mídia são encaminhados em streaming. Cada player
faz requisições recorrentes à API e, consequentemente, à origem do canal.
Qualquer teste de carga, inclusive com k6, também consome banda e recursos da
origem: comece com poucos usuários, aumente gradualmente e teste somente streams
que você tem autorização para acessar.

## Segurança e operação

- Esta API não implementa autenticação. Restrinja o acesso à rede confiável e
  não a publique diretamente na Internet sem adicionar controles de acesso.
- `/channels` retorna os dados dos canais, incluindo os headers configurados.
  Não coloque credenciais ou tokens nesse arquivo se a API estiver acessível a
  clientes não confiáveis.
- A rota `/proxy/{tvg_id}` aceita URLs HTTP/HTTPS para buscar recursos. Proteja
  o serviço contra acesso não autorizado e contra uso como proxy para destinos
  que não deveriam ser acessíveis a partir do servidor.
- A configuração não valida se a origem é licenciada ou autorizada. Configure
  apenas streams e headers que você tem permissão para usar.
