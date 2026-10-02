# Tutorial pessoal — Luvics Clima no Ponto
**Tech.luvics · Uso interno · Outubro 2026**

Este documento é o seu mapa do projeto: o que cada peça faz, o que você configurou no Render e no Resend, e como manter/recriar tudo se precisar.

---

## 1. Visão geral do sistema

```
[Cliente no navegador]
        │
        │  HTML/CSS/JS (mapa Leaflet, formulário)
        ▼
  GitHub Pages / tech.luvics.com.br
  (parte ESTÁTICA — front)
        │
        │  fetch() → API
        ▼
  Render.com  (parte PYTHON — back)
  app.py + Flask + Gunicorn
        │
        ├── Open-Meteo (clima / previsão / histórico)
        ├── Nominatim OSM (busca de endereço)
        └── Resend API HTTPS (envio de e-mail com PDF)
```

| Camada | Onde fica | Função |
|--------|-----------|--------|
| **Front** | GitHub Pages / site tech.luvics | Página do mapa, busca, botões grátis/pago |
| **API** | Render (serviço web Python) | Gera PDF, busca clima, envia e-mail |
| **E-mail** | Resend (API HTTPS) | Entrega o PDF no e-mail do cliente |
| **Dados clima** | Open-Meteo (gratuito) | Temperatura, previsão, histórico |
| **Geocode** | Nominatim OpenStreetMap | Transforma texto em lat/lon |

**URL da API (exemplo do seu deploy):**  
`https://api-clima-kc8m.onrender.com`

**URL do app (front):**  
`https://tech.luvics.com.br/luvics_clima/static/`

**Landing do produto:** rota `/clima` no site  
**Home:** card do produto apontando para `/clima` e para o app

---

## 2. O que é o Render (e por que você usa)

### 2.1 Em uma frase
**Render** é a hospedagem do **backend Python**. Ele fica ligado 24h (com ressalvas no plano free), recebe as chamadas `/api/report`, `/api/geocode`, `/api/health` e devolve o PDF.

### 2.2 Por que não só GitHub Pages?
GitHub Pages só serve **arquivos estáticos** (HTML, CSS, JS).  
Não roda Python, não gera PDF no servidor, não guarda senha de e-mail com segurança, não chama SMTP/API de forma confiável a partir do browser (e expondo chaves seria perigoso).

Por isso:
- **Front** → GitHub / domínio tech.luvics  
- **API** → Render  

### 2.3 Plano free — limites importantes
| Limite | Efeito no seu projeto |
|--------|------------------------|
| Serviço “dorme” após ~15 min sem uso | 1ª request pode demorar 30–60 s (cold start) |
| Timeout de request ~30 s | Por isso o mapa **não** baixa tiles OSM no servidor (timeout) |
| **SMTP bloqueado** (portas 25, 465, 587) desde set/2025 | Gmail SMTP **não funciona** no free → use **Resend via HTTPS** |
| Recursos limitados de CPU/RAM | Evite processos pesados longos |

### 2.4 O que você configurou no Render

**Serviço web**
- Tipo: Web Service  
- Runtime: Python  
- Build: `pip install -r requirements.txt`  
- Start: `gunicorn app:app --timeout 120 --workers 1 --threads 2`  
- Plano: Free (ou pago se um dia quiser SMTP direto)

**Arquivos no repositório da API**
- `app.py` — toda a lógica  
- `requirements.txt` — flask, flask-cors, requests, fpdf2, pillow, gunicorn  
- `render.yaml` (opcional) — declara build/start  

**Variáveis de ambiente (Environment) — o essencial**

| Variável | Para que serve |
|----------|----------------|
| `RESEND_API_KEY` | Chave da Resend (`re_...`). **Prioridade** para enviar e-mail |
| `EMAIL_FROM` | Remetente, ex.: `Luvics Clima <noreply@email.luvics.com.br>` |
| `EMAIL_HOST` | Só se usar SMTP (plano pago): `smtp.gmail.com` |
| `EMAIL_PORT` | SMTP: `587` |
| `EMAIL_USER` | Conta Gmail (SMTP) |
| `EMAIL_PASS` | Senha de **app** do Google (SMTP) — **nunca** no código-fonte |
| `USE_STATICMAP` | `0` (padrão) = mapa local rápido; `1` = tenta tiles OSM (pode estourar timeout) |

**Regra do código:** se existe `RESEND_API_KEY`, usa Resend. Senão tenta SMTP (que no free falha com `Network is unreachable`).

### 2.5 Endpoints da API

| Método | Rota | Função |
|--------|------|--------|
| GET | `/api/health` | `{ ok, email, service }` — badge “API online · e-mail OK” |
| GET | `/api/email-status` | Confere se e-mail está configurado (sem expor senha) |
| GET | `/api/geocode?q=...` | Busca endereço (Nominatim, Brasil) |
| POST | `/api/report` | Body JSON `{ lat, lon, email, mode: "free"|"full" }` → PDF + tentativa de e-mail |

Headers de resposta úteis no front:
- `X-Luvics-Emailed: 1|0`  
- `X-Luvics-Email-Error: ...` (se falhou o envio)

### 2.6 Problemas que você já resolveu no Render

1. **500 / Failed to fetch (~30 s)**  
   - Causa: `staticmap` baixando muitos tiles OSM → timeout  
   - Solução: mapa gerado localmente com Pillow (círculo + texto), sem rede  

2. **E-mail: `[Errno 101] Network is unreachable`**  
   - Causa: plano free bloqueia SMTP  
   - Solução: Resend via HTTPS (`api.resend.com`)  

3. **Senha de app Gmail no código**  
   - Risco de vazamento no GitHub  
   - Solução: só em Environment Variables; se vazou, **revogar** no Google e gerar outra  

### 2.7 Comandos úteis (teste rápido)

```bash
# Saúde
curl -s https://SEU-SERVICO.onrender.com/api/health

# Relatório (salva PDF)
curl -s -X POST "https://SEU-SERVICO.onrender.com/api/report" \
  -H "Content-Type: application/json" \
  -d '{"lat":-21.1775,"lon":-47.8103,"email":"cliente@email.com","mode":"free"}' \
  -o teste.pdf -w "%{http_code}\n"
```

---

## 3. O que é o Resend (e por que você usa)

### 3.1 Em uma frase
**Resend** é o serviço que **envia o e-mail com o PDF anexado**, via API HTTPS. Substitui o Gmail SMTP no plano free do Render.

### 3.2 Por que não Gmail SMTP no free?
Render free **bloqueia** conexões de saída nas portas de e-mail clássicas (25, 465, 587).  
A API da Resend usa **HTTPS (443)**, que não é bloqueada.

### 3.3 Conta e limites (free típico)
- ~100 e-mails/dia, ~3000/mês (confira no painel atual)  
- Domínios verificados limitados (ex.: até 3 no free em atualizações recentes)  
- Sem domínio verificado: **só envia para o e-mail da sua conta Resend**  

### 3.4 O que você fez no Resend (checklist real)

#### A) Criar conta e API Key
1. [resend.com](https://resend.com) → cadastro  
2. **API Keys** → Create → copiar `re_...`  
3. Colar no Render: `RESEND_API_KEY=re_...`

#### B) Fase de teste (só para você)
- Remetente padrão: `onboarding@resend.dev`  
- **Só entrega** no e-mail com que você se cadastrou na Resend  
- Serve para validar o fluxo PDF + e-mail  

#### C) Enviar para o **cliente** (domínio verificado)
1. Resend → **Domains** → Add Domain  
2. Você usou algo como: **`email.luvics.com.br`**  
3. Copiar registros DNS (TXT/CNAME/MX conforme o painel)  
4. Colar no DNS do domínio (Registro.br, Cloudflare, etc.)  
5. Se Cloudflare: CNAME de e-mail com nuvem **cinza (DNS only)**  
6. Esperar status **Verified** (minutos a algumas horas)  
7. No Render, definir:

```text
EMAIL_FROM=Luvics Clima <noreply@email.luvics.com.br>
```

O endereço `noreply@...` **não precisa** existir como caixa de entrada.  
O que importa é o **domínio** estar verificado e o `from` usar esse domínio.

#### D) Erro clássico que você bateu
> Só consigo mandar para mim mesmo  

| Causa | Correção |
|-------|----------|
| `from` ainda `@resend.dev` | Mudar `EMAIL_FROM` para `@email.luvics.com.br` |
| Domínio ainda Pending | Completar DNS até **Verified** |
| Domínio Verified + FROM certo | Envia para qualquer cliente |

Mensagem típica da API (403):  
*You can only send testing emails to your own email address... verify a domain and change the from address...*

### 3.5 Como o `app.py` usa a Resend
- POST `https://api.resend.com/emails`  
- Header: `Authorization: Bearer RESEND_API_KEY`  
- Body JSON: `from`, `to`, `subject`, `text`, `attachments` (PDF em base64)  
- Timeout ~30 s  

---

## 4. Front (site estático)

### 4.1 App do clima
Arquivo principal: `index.html` (mapa Leaflet + painel).

Configuração crítica:

```js
const API = "https://api-clima-kc8m.onrender.com";  // SEM barra no final
```

Se mudar a URL do Render, atualize essa linha e faça deploy do front.

### 4.2 Fluxo do usuário no app
1. Abre o mapa (padrão Ribeirão Preto; ajustável)  
2. Busca endereço **ou** clica no mapa (satélite útil na zona rural)  
3. Informa e-mail  
4. **Grátis** ou **Completo (simulação)**  
5. Browser baixa o PDF; se Resend ok, também chega no e-mail  

### 4.3 Páginas de marketing que você gerou
| Arquivo | Uso |
|---------|-----|
| `luvics_clima_landing.html` | Landing em `/clima` — explica produto e leva ao app |
| `tech_luvics_home.html` | Home com card **Luvics Clima no Ponto** entre os produtos |

Links importantes:
- Produto: `/clima`  
- App: `https://tech.luvics.com.br/luvics_clima/static/`  

---

## 5. Produto (o que vende / o que é grátis)

| | Grátis | Pago (a partir de R$ 9,90/mês · 1 ponto) |
|--|--------|------------------------------------------|
| Temperatura atual | ✓ | ✓ |
| Mapa raio 1 km | ✓ | ✓ |
| PDF + e-mail | ✓ | ✓ |
| Previsão 7 dias | | ✓ |
| Chuva, vento, umidade | | ✓ |
| Histórico 30 dias | | ✓ |
| Noites Tmin ≤ 5 °C | | ✓ |
| Envio diário automático | | ✓ (conceito do plano; rotina diária pode ser evolução futura no backend) |

Pacotes mencionados no material:
- 5 pontos R$ 19,90  
- 10 pontos R$ 29,90  
- ponto extra +R$ 5  

**Disclaimer:** dados Open-Meteo; material orientativo; não substitui ART/laudo/seguro.

---

## 6. Arquivos do backend (o que cada um faz)

| Arquivo | Função |
|---------|--------|
| `app.py` | Flask: health, geocode, report, PDF, e-mail (Resend ou SMTP) |
| `requirements.txt` | Dependências pip |
| `render.yaml` | Build/start no Render (opcional) |
| `DEPLOY.txt` | Notas antigas de deploy (SMTP); preferir este tutorial |

**Funções-chave no `app.py`**
- `fetch_climate` / `summarize` — Open-Meteo  
- `make_map_png` — mapa local (Pillow) por padrão  
- `build_pdf_free` / `build_pdf_full` — FPDF  
- `send_report_email_resend` — HTTPS Resend  
- `send_report_email_smtp` — só útil em plano **pago** Render  

---

## 7. Segurança (não esquecer)

1. **Nunca** commitar senha de app Gmail ou `RESEND_API_KEY` no GitHub.  
2. Se já vazou senha de app: Google → Segurança → Senhas de app → **revogar** → gerar nova.  
3. Chaves só em **Environment** do Render.  
4. CORS está aberto em `/api/*` (`origins: *`) para o front no domínio tech.luvics.  

---

## 8. Operação do dia a dia

### Redeploy da API
1. Alterar `app.py` / requirements no repo da API  
2. Push → Render rebuild automático  
3. Conferir logs no painel se falhar  

### Cold start (free)
Se ninguém usou o serviço ~15 min, a primeira chamada demora.  
Opções futuras: ping periódico (cron), plano pago, ou avisar o usuário “aguarde até 1 min”.

### Trocar domínio de e-mail
1. Verificar novo domínio na Resend  
2. Atualizar `EMAIL_FROM` no Render  
3. Testar com e-mail que **não** seja o seu  

### Trocar URL da API
1. Novo serviço Render → nova URL  
2. Atualizar `const API` no `index.html` do front  
3. Deploy do front  

---

## 9. Checklist “está tudo ok?”

- [ ] `GET /api/health` → `"ok": true` e `"email": true`  
- [ ] Badge no front: **API online · e-mail OK**  
- [ ] PDF grátis baixa no navegador  
- [ ] E-mail chega em **outro** endereço (cliente), não só no seu  
- [ ] `EMAIL_FROM` usa `@email.luvics.com.br` (ou o domínio Verified)  
- [ ] Domínio na Resend = **Verified**  
- [ ] Landing `/clima` e home com card do produto  

---

## 10. Problemas → causa → ação

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| Failed to fetch / 500 ~30s | Timeout (mapa/tiles) ou worker morto | Mapa local; logs Render; cold start |
| Network is unreachable no e-mail | SMTP no free | Usar Resend + `RESEND_API_KEY` |
| Só envia para mim | FROM `@resend.dev` ou domínio não Verified | Verificar domínio + `EMAIL_FROM` |
| API offline no badge | URL errada ou serviço dormindo/crash | Conferir `const API` e logs Render |
| Geocode vazio | Query curta ou Nominatim | ≥ 3 caracteres; User-Agent já está no app |
| PDF ok, e-mail não | Resend 4xx | Ver `X-Luvics-Email-Error` e logs Resend |

---

## 11. Resumo em 30 segundos

- **Render** = servidor Python da API (PDF + clima). Free não manda SMTP.  
- **Resend** = manda o e-mail por HTTPS; domínio verificado = envia para o cliente.  
- **Front** = mapa e formulário; aponta para a URL do Render.  
- **Grátis** prova o fluxo; **pago** é o upsell (previsão, histórico, rotina).  
- Chaves e senhas **só** no Environment do Render.  

---

*Documento gerado a partir do deploy real do Luvics Clima no Ponto (Render + Resend + front tech.luvics). Atualize URLs e nomes de domínio se mudar o serviço.*
