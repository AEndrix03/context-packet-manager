# Documentation And Commit Policy

## Aggiornamento documentazione
Dopo ogni sviluppo rilevante:
1. aggiornare i documenti tecnici in `docs/` impattati dalla modifica,
2. aggiornare il README della funzionalita/modulo coinvolto (`README.md` root o README locali),
3. documentare nuove opzioni CLI, nuovi artifact o cambi incompatibili.

## Politica commit
Dopo ogni modifica rilevante eseguire un commit dedicato con prefissi standard:
- `feat: ...`
- `fix: ...`
- `docs: ...`
- `test: ...`
- `chore: ...`

Messaggi consigliati: verbo all'infinito/imperativo, scopo chiaro, opzionale scope (`feat(query): ...`).

## Regola pratica
Meglio piu commit piccoli e coerenti che un commit grande eterogeneo.
