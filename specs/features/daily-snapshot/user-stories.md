# Histórias de Usuário — Snapshot diário

## Personas

- **Felix (P1)** — dono; consulta o dia repetidamente pelo chat e pela `/day`.
- **Sistema (não-persona)** — outros services que precisam dos totais consolidados (`day-close`, `weekly-report`).

---

### US-001 — Ver totais do dia sem esperar

**Como** Felix,
**Quero** abrir `/chat` de manhã e ver "0 kcal, 0 ml" (não erro),
**Para que** a app pareça "pronta" mesmo antes do primeiro registro.

**Critérios de aceitação resumidos:**
- [ ] `GET /days/today` sem registros ainda → 200 com todos os totais em 0.
- [ ] `DayLogRepository.get_or_create` garante `day_log` sempre existe pra hoje.
- [ ] Sem 404 no dia atual.

**Cobertura**: SP-90.

---

### US-002 — Consultar dia passado

**Como** Felix,
**Quero** olhar o dia 15/07 e ver `kcal_in`, `water_ml` etc consolidados,
**Para que** eu possa auditar um dia específico.

**Critérios de aceitação resumidos:**
- [ ] `GET /days/2026-07-15` retorna 200 com totals + records se `day_log` existe.
- [ ] Dia sem `day_log` → 404 com `code=day_not_found` (não criamos automaticamente pra dias passados).

**Cobertura**: SP-91.

---

### US-003 — Registrar tarde da noite sem "vazar" para o próximo dia

**Como** Felix,
**Quero** enviar "café" às 23:50 de 12/jul (BRT) e ver esse café no snapshot de 12/jul,
**Para que** o dia local respeite meu fuso.

**Critérios de aceitação resumidos:**
- [ ] `local_today('America/Sao_Paulo')` retorna `2026-07-12` mesmo que UTC seja `2026-07-13 02:50`.
- [ ] `day_log.log_date=2026-07-12` recebe o registro.
- [ ] Snapshot do dia 12 é atualizado.

**Cobertura**: SP-92.

---

### US-004 — Confiar que o total reflete os itens vivos

**Como** Felix,
**Quero** que ao deletar um item o total do dia caia na mesma request,
**Para que** eu nunca veja o total "stale".

**Critérios de aceitação resumidos:**
- [ ] `DELETE /records/food-items/{id}` → recompute → snapshot atualizado antes do 200.
- [ ] `deleted_at IS NULL` em todo `SUM` — item deletado desaparece do total.

**Cobertura**: INV-4, integração com [`record-deletion`](../record-deletion/).

---

### US-005 — Ver items que precisam de atenção

**Como** Felix,
**Quero** que o snapshot me mostre "3 itens sem catálogo" e "2 itens precisam de confirmação",
**Para que** eu possa clicar e resolver antes de fechar o dia.

**Critérios de aceitação resumidos:**
- [ ] `warnings` do snapshot inclui `{code, entity, item_id, detected_name}` para cada `no_catalog_hit` e `needs_confirmation`.
- [ ] Barra de totais (SP-116) mostra contador clicável.
- [ ] Ao resolver (correção, foto de rótulo, cadastro manual), próximo recompute limpa o warning.

**Cobertura**: RF-011 + integração com [`assistant-message-rendering`](../assistant-message-rendering/).

---

### US-006 — Não perder história ao mudar catálogo

**Como** Felix,
**Quero** atualizar valores do seed TBCA (arroz: 124 → 130 kcal) sem que meu histórico mude,
**Para que** dias passados continuem sendo o que eu registrei.

**Critérios de aceitação resumidos:**
- [ ] `food_items.kcal` já materializado — atualizar `nutrient_facts` não muda item existente.
- [ ] Snapshot de dia passado só muda se recompute for chamado manualmente com script.
- [ ] Dia fechado (`INV-5`) nunca é recomputado.

**Cobertura**: INV-4 + INV-5 + arquitetura de materialização em [`food-logging`](../food-logging/).

---

### US-007 — Serializar recompute com version

**Como** Felix (via cliente web),
**Quero** que a barra de totais tenha um `snapshot_version` monotônico,
**Para que** o cliente saiba quando revalidar cache local.

**Critérios de aceitação resumidos:**
- [ ] Cada upsert incrementa `version` (`version = version + 1`).
- [ ] Payload de resposta inclui `snapshot_version`.
- [ ] Cliente pode comparar `version` recebido vs. em cache.

**Cobertura**: RF-010.
