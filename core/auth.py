"""
Modulo de autenticacao do App 10M (Etapa 3 - multi-usuario).

Centraliza:
  - Hash de senha com bcrypt (rounds=12, padrao seguro 2026).
  - Verificacao de senha contra hash armazenado.
  - Helper de acesso ao usuario logado e seu household, lendo do
    st.session_state. Se ninguem estiver logado, levanta RuntimeError
    com mensagem amigavel — usado por core/database.py para impedir
    queries sem contexto de tenant.

Por que bcrypt e nao argon2 ou scrypt? bcrypt e o padrao de facto em
Python web ha mais de 15 anos, esta na lib `bcrypt` oficial (mantida),
e e suficiente para o threat model de um app pessoal (4 usuarios, sem
exposicao publica). Argon2 seria sobre-engenharia aqui.

Por que rounds=12? E o equivalente moderno a "uns 250-400ms por hash
em hardware de 2026" — alto o suficiente para inviabilizar brute-force
e baixo o suficiente para nao travar o login. Rounds=10 (default antigo)
e fraco hoje; rounds=14+ comeca a virar UX ruim.
"""
import bcrypt
import streamlit as st


def hash_password(plain: str) -> str:
    """Gera o hash bcrypt de uma senha em claro. Retorna string ASCII de 60 chars."""
    if not isinstance(plain, str) or not plain:
        raise ValueError("Senha vazia nao pode ser hasheada.")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Compara senha em claro contra hash bcrypt armazenado.
    Retorna False (nao raise) para qualquer falha — evita oraculo de timing
    diferente entre 'usuario nao existe' e 'senha errada'.
    """
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Hash mal-formado ou tipo errado — sempre falha.
        return False


def get_current_user() -> dict:
    """
    Retorna o dict do usuario logado a partir do st.session_state. Esperado:
      {'id': int, 'nome': str, 'email': str, 'papel': str,
       'household_id': int, 'household_nome': str}

    Levanta RuntimeError se ninguem estiver logado — usado como guarda nas
    queries do banco para evitar vazamento entre households por bug de codigo.
    """
    user = st.session_state.get("user")
    if not user or "household_id" not in user:
        raise RuntimeError(
            "Sessao sem usuario logado. Faça login antes de acessar dados."
        )
    return user


def get_current_household_id() -> int:
    """Atalho para get_current_user()['household_id']."""
    return int(get_current_user()["household_id"])


def is_admin() -> bool:
    """True se o usuario logado tem papel='admin' (controle de gestao de usuarios)."""
    try:
        return get_current_user().get("papel") == "admin"
    except RuntimeError:
        return False


def logout():
    """Limpa session_state e volta para tela de login."""
    st.session_state.clear()
    st.rerun()


# household que hoje enxerga SO a Renda Passiva do Ricardo (login "ladrons").
# Fica como constante nomeada, nao espalhada como numero magico pelo codigo.
HOUSEHOLD_ID_RENDA_PASSIVA_ONLY = 2


def restrito_a_renda_passiva() -> bool:
    """
    True quando o login logado deve ver SO a pagina de Renda Passiva do
    Ricardo — sem Lancamentos, Dashboard, Patrimonio, Projecoes ou
    Configuracoes, e sem a aba de Patrimonio dentro do proprio modulo Ricardo.

    Checado por household_id (o unico identificador que nao muda), e nao por
    `papel` ou `nome` do usuario — esses dois campos ja foram trocados de
    valor nesta mesma conta numa sessao anterior (virou "Ricardo" e voltou a
    ser "Ladrões"), entao amarrar a regra neles seria fragil.
    """
    try:
        return get_current_household_id() == HOUSEHOLD_ID_RENDA_PASSIVA_ONLY
    except RuntimeError:
        return False
