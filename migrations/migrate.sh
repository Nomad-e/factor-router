#!/usr/bin/env bash
# Uso (a partir de qualquer pasta):
#   ./migrations/migrate.sh 005_openrouter_credits_state.sql
#   ./migrations/migrate.sh 005              # único ficheiro que começa por 005_
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${ROOT_DIR}/.env"

usage() {
  echo "Uso: $0 <ficheiro.sql | prefixo, ex. 005>" >&2
  echo "  Lê DATABASE_URL de ${ENV_FILE}" >&2
  exit 1
}

[[ $# -ge 1 ]] || usage
arg="$1"

resolve_sql_path() {
  local a="$1"
  if [[ -f "$a" ]]; then
    echo "$(cd "$(dirname "$a")" && pwd)/$(basename "$a")"
    return 0
  fi
  if [[ -f "$SCRIPT_DIR/$a" ]]; then
    echo "$SCRIPT_DIR/$a"
    return 0
  fi
  if [[ "$a" == *.sql ]]; then
    echo "Ficheiro não encontrado: $a (nem em $SCRIPT_DIR)" >&2
    return 1
  fi
  local matches
  matches=( "$SCRIPT_DIR"/"${a}"_*.sql )
  if [[ ${#matches[@]} -eq 1 && -f "${matches[0]}" ]]; then
    echo "${matches[0]}"
    return 0
  fi
  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "Nenhuma migração com prefixo '${a}_' em $SCRIPT_DIR" >&2
    return 1
  fi
  echo "Ambíguo: vários ficheiros para prefixo '$a':" >&2
  printf '  %s\n' "${matches[@]}" >&2
  return 1
}

read_database_url() {
  [[ -f "$ENV_FILE" ]] || { echo "Falta ${ENV_FILE}" >&2; return 1; }
  local line val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//$'\r'/}"
    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" == DATABASE_URL=* ]]; then
      val="${line#DATABASE_URL=}"
      val="${val#\"}"; val="${val%\"}"
      val="${val#\'}"; val="${val%\'}"
      val="${val#"${val%%[![:space:]]*}"}"
      val="${val%"${val##*[![:space:]]}"}"
      if [[ -n "$val" ]]; then
        printf '%s' "$val"
        return 0
      fi
    fi
  done < "$ENV_FILE"
  echo "DATABASE_URL não definido em ${ENV_FILE}" >&2
  return 1
}

SQL_PATH="$(resolve_sql_path "$arg")" || exit 1
DATABASE_URL="$(read_database_url)" || exit 1
DATABASE_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"

if ! command -v psql >/dev/null 2>&1; then
  echo "Comando 'psql' não encontrado (instala cliente PostgreSQL)." >&2
  exit 1
fi

echo "→ Migração: $SQL_PATH"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SQL_PATH"
echo "→ OK"
