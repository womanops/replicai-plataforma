"""Quem é o cliente, e o que é dele.

Até aqui a plataforma não perguntava nada: quem alcançasse a porta criava
trabalho, e todos os trabalhos viviam na mesma pasta. Para vender um plano
isso não serve — é preciso saber de quem é cada peça, quanto cada um gastou,
e impedir que um veja o do outro.

Guardado em disco, como o resto: a API pode cair e voltar, e conta perdida é
cliente perdido.

**Nada de segredo é guardado em claro.** A senha vira hash com `scrypt`, que é
lento de propósito — quem levar o arquivo não sai testando senha em massa. A
chave de API é sorteada com entropia suficiente para não se adivinhar, e dela
guarda-se só o resumo: aparece uma vez, na criação, e nunca mais.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# custo do scrypt. 2^14 leva cerca de 60ms nesta máquina: incômodo para quem
# tenta milhões de senhas, imperceptível para quem entra uma vez.
CUSTO = 2 ** 14
BLOCO, PARALELO = 8, 1

PREFIXO_CHAVE = "rpl_"
# e-mail sem o que vira marcação: `a<img src=x onerror=...>@b.co` passava no
# teste de "tem arroba e ponto" e ia parar na lista de quem tem acesso, que a
# colega de agência abre. A tela escapa o que mostra, e isto é o segundo muro:
# o endereço errado não chega a ser guardado.
EMAIL = re.compile(r"^[^@\s<>\"'&\\/]+@[^@\s<>\"'&\\/]+\.[^@\s<>\"'&\\/]+$")


class ContaInvalida(ValueError):
    """O que foi pedido não dá para fazer, e o motivo é do cliente."""


def pasta() -> Path:
    from api.trabalhos import pasta_base
    p = pasta_base() / "_contas"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Conta:
    id: str
    nome: str
    email: str
    criada: str = ""
    # "sem" é o estado de quem não assinou: a conta nasce da assinatura, e
    # um plano que não existe mais ("demo") deixava a conta num degrau
    # fantasma. É o `uso.PLANO_PADRAO`, repetido aqui para não importar
    # `uso` dentro do dataclass
    plano: str = "sem"
    ativa: bool = True
    senha: str = ""
    chaves: list[dict] = field(default_factory=list)
    # cobrança: `plano` é o que foi comprado, `pago_ate` é até quando vale
    asaas_cliente: str = ""
    asaas_assinatura: str = ""
    plano_pedido: str = ""
    pago_ate: str = ""
    em_atraso: bool = False
    # as medidas que a pessoa usa e o catálogo não tem. Digitar 1200×1600 a
    # cada trabalho é trabalho que a plataforma devia lembrar
    medidas: list[dict] = field(default_factory=list)
    # as fontes da marca. Sem elas, trocar o texto de uma peça do PSD sai na
    # letra da casa — que é o erro mais difícil de ver no olho
    fontes: list[dict] = field(default_factory=list)
    # as outras pessoas da agência, cada uma com o login dela. O dono não está
    # aqui: ele é o `email`/`senha` da conta, e é a pessoa que não se remove
    pessoas: list[dict] = field(default_factory=list)
    # quem paga não é quem usa: em agência o financeiro recebe a nota e o
    # diretor de arte recebe o acesso. Dois e-mails, dois assuntos
    email_financeiro: str = ""
    # convite do DONO: o acesso dele nasce sem senha e vem por e-mail quando o
    # pagamento é aprovado. Guarda-se o resumo, nunca o convite em claro
    convite: str = ""
    convite_ate: str = ""
    ultimo: str = ""               # quando o dono entrou pela última vez

    def em_json(self, quem: str = "") -> dict:
        """Sem segredo: é isto que pode sair da API.

        `quem` é a pessoa da conta que está olhando — com várias pessoas no
        mesmo acesso, a tela precisa saber dizer "você" para a pessoa certa.
        """
        eu = next((p for p in self.pessoas if p.get("id") == quem), None)
        return {"id": self.id, "nome": self.nome, "email": self.email,
                "eu": {"id": quem or "dono",
                       "nome": (eu or {}).get("nome") or self.nome,
                       "email": (eu or {}).get("email") or self.email,
                       "dono": quem in ("", "dono")},
                "acessos": 1 + len(self.pessoas),
                "criada": self.criada, "plano": self.plano, "ativa": self.ativa,
                "pago_ate": self.pago_ate, "em_atraso": self.em_atraso,
                "assinatura": bool(self.asaas_assinatura),
                "medidas": list(self.medidas),
                "fontes": [{k: f.get(k) for k in ("id", "familia", "estilo", "nome")}
                           for f in self.fontes],
                "chaves": [{"id": c["id"], "apelido": c.get("apelido", ""),
                            "criada": c.get("criada", ""), "fim": c.get("fim", "")}
                           for c in self.chaves]}


# quantas medidas próprias cabem na conta. É lista de atalho, não catálogo:
# passando disso a grade vira a lista enorme de que ela é o remédio
MAX_MEDIDAS = 40


def guardar_medida(conta: Conta, w: int, h: int, nome: str = "") -> list[dict]:
    """Guarda uma medida fora do catálogo na conta de quem pediu.

    O motor resolve qualquer `livre-LARGxALT` sozinho, então o que fica
    gravado é só o atalho: o id, a medida e o apelido. Nada aqui muda como a
    peça é feita.
    """
    # o mesmo limite do motor, lido de lá: duas constantes iguais em arquivos
    # diferentes é uma delas errada daqui a um mês
    from motor.replica import LIVRE_MAX, LIVRE_MIN
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        raise ContaInvalida("a medida é em pixels, nos dois lados")
    if not (LIVRE_MIN <= w <= LIVRE_MAX and LIVRE_MIN <= h <= LIVRE_MAX):
        raise ContaInvalida(
            f"a medida vai de {LIVRE_MIN} a {LIVRE_MAX} pixels de cada lado")
    ident = f"livre-{w}x{h}"
    if any(m.get("id") == ident for m in conta.medidas):
        return list(conta.medidas)          # já era dela: não duplica
    if len(conta.medidas) >= MAX_MEDIDAS:
        raise ContaInvalida(f"são no máximo {MAX_MEDIDAS} medidas guardadas; "
                            "tire uma que não usa mais")
    conta.medidas.append({"id": ident, "w": w, "h": h,
                          "nome": (nome or f"{w}×{h}").strip()[:40],
                          "criada": _agora()})
    _gravar(conta)
    return list(conta.medidas)


def esquecer_medida(conta: Conta, ident: str) -> list[dict]:
    """Tira uma medida guardada. As peças já feitas com ela não são tocadas."""
    conta.medidas = [m for m in conta.medidas if m.get("id") != ident]
    _gravar(conta)
    return list(conta.medidas)


# o teto de cada arquivo de fonte e quantos cabem na conta. Uma fonte de
# texto completa passa longe de 2 MB; o que passa de 6 é arquivo errado
FONTE_MAX = 6_000_000
MAX_FONTES = 24
TIPOS_DE_FONTE = {".ttf", ".otf", ".woff", ".woff2"}


def chave_da_fonte(*partes: str) -> str:
    """O nome da fonte sem espaço, hífen nem caixa.

    O PSD pede `FuturaICG-Bold`; o arquivo se apresenta como família
    "Futura ICG" e estilo "Bold". É a mesma fonte, e só comparando assim um
    acha o outro.
    """
    junto = "".join(p or "" for p in partes)
    return "".join(c for c in junto.lower() if c.isalnum())


def _nomes_da_fonte(caminho: Path) -> tuple[str, str]:
    """Família e estilo, lidos de dentro do arquivo — não do nome dele."""
    from PIL import ImageFont
    f = ImageFont.truetype(str(caminho), 16)
    familia, estilo = f.getname()
    return (familia or "").strip(), (estilo or "").strip()


def pasta_das_fontes(conta: Conta) -> Path:
    p = pasta() / "fontes" / conta.id
    p.mkdir(parents=True, exist_ok=True)
    return p


def guardar_fonte(conta: Conta, nome: str, dados: bytes) -> dict:
    """Guarda um arquivo de fonte na conta e devolve o que foi guardado."""
    ext = Path(nome or "").suffix.lower()
    if ext not in TIPOS_DE_FONTE:
        raise ContaInvalida("mande .ttf, .otf, .woff ou .woff2")
    if len(dados) > FONTE_MAX:
        raise ContaInvalida(f"a fonte passa de {FONTE_MAX // 1_000_000} MB")
    if len(conta.fontes) >= MAX_FONTES:
        raise ContaInvalida(f"são no máximo {MAX_FONTES} fontes guardadas")
    destino = pasta_das_fontes(conta) / re.sub(r"[^A-Za-z0-9._-]", "_", Path(nome).name)
    destino.write_bytes(dados)
    try:
        familia, estilo = _nomes_da_fonte(destino)
    except Exception:
        destino.unlink(missing_ok=True)
        raise ContaInvalida("não consegui ler esse arquivo como fonte")
    item = {"id": chave_da_fonte(familia, estilo) or destino.stem.lower(),
            "familia": familia, "estilo": estilo,
            "nome": destino.name, "criada": _agora()}
    conta.fontes = [f for f in conta.fontes if f.get("id") != item["id"]] + [item]
    _gravar(conta)
    return item


def esquecer_fonte(conta: Conta, ident: str) -> list[dict]:
    achada = next((f for f in conta.fontes if f.get("id") == ident), None)
    if achada:
        (pasta_das_fontes(conta) / achada["nome"]).unlink(missing_ok=True)
    conta.fontes = [f for f in conta.fontes if f.get("id") != ident]
    _gravar(conta)
    return list(conta.fontes)


def fonte_de(conta: Conta, familia: str) -> dict | None:
    """A fonte guardada que atende `familia`, como o PSD a pede."""
    procurada = chave_da_fonte(familia)
    if not procurada:
        return None
    for f in conta.fontes:
        if f.get("id") == procurada or chave_da_fonte(f.get("familia"), f.get("estilo")) == procurada:
            return f
    # `FuturaICG-Bold` quando só a família foi enviada, sem o corpo bold
    for f in conta.fontes:
        if chave_da_fonte(f.get("familia")) == procurada:
            return f
    return None


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _amassar(senha: str, sal: bytes) -> str:
    bruto = hashlib.scrypt(senha.encode(), salt=sal, n=CUSTO, r=BLOCO, p=PARALELO,
                           maxmem=64 * 1024 * 1024)
    return f"scrypt${CUSTO}${BLOCO}${PARALELO}${sal.hex()}${bruto.hex()}"


def conferir_senha(senha: str, guardado: str) -> bool:
    """Compara em tempo constante: diferença de tempo entrega a senha aos
    poucos para quem mede."""
    try:
        marca, n, r, p, sal, esperado = guardado.split("$")
        if marca != "scrypt":
            return False
        bruto = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal),
                               n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(bruto.hex(), esperado)


def _resumo(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


def _arquivo(ident: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{3,64}", ident or ""):
        raise ContaInvalida("identificador de conta inválido")
    return pasta() / f"{ident}.json"


def _gravar(c: Conta) -> None:
    _arquivo(c.id).write_text(
        json.dumps({"id": c.id, "nome": c.nome, "email": c.email, "criada": c.criada,
                    "plano": c.plano, "ativa": c.ativa, "senha": c.senha,
                    "chaves": c.chaves, "asaas_cliente": c.asaas_cliente,
                    "asaas_assinatura": c.asaas_assinatura,
                    "plano_pedido": c.plano_pedido, "pago_ate": c.pago_ate,
                    "em_atraso": c.em_atraso, "medidas": c.medidas,
                    "fontes": c.fontes, "pessoas": c.pessoas,
                    "email_financeiro": c.email_financeiro,
                    "convite": c.convite, "convite_ate": c.convite_ate,
                    "ultimo": c.ultimo},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")


def _ler(ident: str) -> Conta | None:
    f = _arquivo(ident)
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    # a pasta guarda também índices — chaves, eventos do meio de pagamento — e
    # listar contas tentava lê-los como conta. Quebrava o login depois do
    # primeiro pagamento, que é a pior hora para quebrar.
    if not isinstance(d, dict) or "id" not in d or "email" not in d:
        return None
    try:
        return Conta(**d)
    except TypeError:
        return None          # conta gravada por uma versão com outros campos


def por_id(ident: str) -> Conta | None:
    try:
        return _ler(ident)
    except ContaInvalida:
        return None


def todas() -> list[Conta]:
    saida = []
    for f in sorted(pasta().glob("*.json")):
        c = por_id(f.stem)
        if c:
            saida.append(c)
    return saida


def por_email(email: str) -> Conta | None:
    """A conta de quem usa este e-mail — dono ou qualquer pessoa dela.

    Procurar só pelo dono deixava a pessoa convidada sem porta: ela digitava o
    e-mail certo e ouvia que não existe conta.
    """
    alvo = (email or "").strip().lower()
    for c in todas():
        if c.email == alvo or any(p.get("email") == alvo for p in c.pessoas):
            return c
    return None


def _ident_de(nome: str, email: str) -> str:
    from api.trabalhos import apelido
    base = apelido(nome) or apelido(email.split("@")[0]) or "conta"
    return f"{base[:40]}-{secrets.token_hex(3)}"


def criar(nome: str, email: str, senha: str, plano: str = "sem") -> Conta:
    email = (email or "").strip().lower()
    if not EMAIL.fullmatch(email):
        raise ContaInvalida("e-mail inválido")
    if len(senha or "") < 10:
        raise ContaInvalida("a senha precisa de pelo menos 10 caracteres")
    if por_email(email):
        raise ContaInvalida("já existe conta com esse e-mail")
    c = Conta(id=_ident_de(nome, email), nome=(nome or "").strip() or email,
              email=email, criada=_agora(), plano=plano,
              senha=_amassar(senha, secrets.token_bytes(16)))
    _gravar(c)
    return c


def entrar(email: str, senha: str) -> tuple[Conta, str] | None:
    """Quem é a conta e QUAL PESSOA dela está entrando.

    Saber a pessoa não é vaidade de registro: com três pessoas da agência
    mexendo nas mesmas peças, "quem ajustou isto" é a primeira pergunta — e é
    o que permite tirar o acesso de quem saiu sem trocar a senha dos outros.
    """
    alvo = (email or "").strip().lower()
    c = por_email(alvo)
    if c is None:
        # gasta o mesmo tempo de uma conta que existe: responder rápido quando
        # o e-mail não existe conta quais e-mails existem
        _amassar(senha or "", b"0" * 16)
        return None
    if not c.ativa:
        return None
    for quem in logins(c):
        if quem["email"] != alvo:
            continue
        if not quem["senha"] or not conferir_senha(senha or "", quem["senha"]):
            return None
        _marcar_entrada(c, quem["id"])
        return c, quem["id"]
    return None


def autenticar(email: str, senha: str) -> Conta | None:
    """A conta de quem entrou. `entrar()` diz também qual pessoa."""
    r = entrar(email, senha)
    return r[0] if r else None


# ------------------------------------------------- as pessoas da agência

DONO = "dono"
CONVITE_VALE_HORAS = 48
MIN_SENHA = 10


def logins(conta: Conta) -> list[dict]:
    """Todas as pessoas que podem entrar nesta conta, o dono primeiro.

    O dono não vive na lista `pessoas`: ele é o e-mail e a senha da própria
    conta, e é a pessoa que não se remove. Aqui os dois falam a mesma língua.
    """
    return [{"id": DONO, "nome": conta.nome, "email": conta.email,
             "senha": conta.senha, "dono": True,
             "convite": conta.convite, "convite_ate": conta.convite_ate,
             "ultimo": conta.ultimo}] + [
        {**p, "dono": False} for p in conta.pessoas]


def pessoa_de(conta: Conta, quem: str) -> dict | None:
    return next((q for q in logins(conta) if q["id"] == quem), None)


def acessos_de(conta: Conta) -> int:
    """Quantas pessoas a conta já tem, contando o dono."""
    return 1 + len(conta.pessoas)


def limite_de_acessos(conta: Conta) -> int:
    from api import cobranca, uso
    return uso.limites(cobranca.plano_valendo(conta)).get("acessos", 1)


def _marcar_entrada(conta: Conta, quem: str) -> None:
    """Guarda quando cada pessoa entrou pela última vez.

    É o que responde "esse acesso ainda é usado?" na hora de convidar a quarta
    pessoa numa conta de três.
    """
    agora = _agora()
    if quem == DONO:
        conta.ultimo = agora
    else:
        for p in conta.pessoas:
            if p.get("id") == quem:
                p["ultimo"] = agora
    _gravar(conta)


def _token() -> tuple[str, str]:
    """Um convite e o resumo dele. Guarda-se o resumo: arquivo roubado não
    abre conta de ninguém, como já é com a chave de API."""
    bruto = secrets.token_urlsafe(32)
    return bruto, _resumo(bruto)


def _ate_daqui(horas: int = CONVITE_VALE_HORAS) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=horas)).isoformat(
        timespec="seconds")


def convidar(conta: Conta, nome: str, email: str) -> tuple[dict, str]:
    """Abre um acesso para mais uma pessoa da agência. Devolve o convite.

    O convite é um endereço de uso único com prazo: a senha nasce escolhida
    pela pessoa. Senha mandada por e-mail fica guardada para sempre em caixa de
    entrada, telefone e backup de quem recebeu.
    """
    email = (email or "").strip().lower()
    if not EMAIL.fullmatch(email):
        raise ContaInvalida("e-mail inválido")
    if por_email(email):
        raise ContaInvalida("esse e-mail já tem acesso")
    limite = limite_de_acessos(conta)
    if not limite:
        raise ContaInvalida("esta conta não tem plano ativo")
    if acessos_de(conta) >= limite:
        raise ContaInvalida(
            f"o plano permite {limite} "
            f"{'pessoa' if limite == 1 else 'pessoas'} e já são {acessos_de(conta)}. "
            "Remova um acesso ou suba de plano")
    bruto, resumo = _token()
    pessoa = {"id": f"p-{secrets.token_hex(3)}", "nome": (nome or "").strip() or email,
              "email": email, "senha": "", "criada": _agora(),
              "convite": resumo, "convite_ate": _ate_daqui(), "ultimo": ""}
    conta.pessoas.append(pessoa)
    _gravar(conta)
    return pessoa, bruto


def remover_pessoa(conta: Conta, quem: str) -> bool:
    """Tira o acesso de quem saiu da agência. O dono não se remove."""
    if quem == DONO:
        raise ContaInvalida("o acesso do dono da conta não se remove")
    antes = len(conta.pessoas)
    conta.pessoas = [p for p in conta.pessoas if p.get("id") != quem]
    if len(conta.pessoas) == antes:
        return False
    _gravar(conta)
    return True


def novo_convite(conta: Conta, quem: str = DONO) -> str:
    """Um convite novo para quem ainda não entrou — ou esqueceu a senha."""
    bruto, resumo = _token()
    if quem == DONO:
        conta.convite, conta.convite_ate = resumo, _ate_daqui()
    else:
        p = next((p for p in conta.pessoas if p.get("id") == quem), None)
        if p is None:
            raise ContaInvalida("essa pessoa não está na conta")
        p["convite"], p["convite_ate"] = resumo, _ate_daqui()
    _gravar(conta)
    return bruto


def _vencido(ate: str) -> bool:
    try:
        return datetime.fromisoformat(ate) < datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


def dono_do_convite(bruto: str) -> tuple[Conta, dict] | None:
    """De quem é este convite, se ainda vale."""
    resumo = _resumo(bruto or "")
    if not bruto:
        return None
    for c in todas():
        for quem in logins(c):
            if quem.get("convite") and hmac.compare_digest(quem["convite"], resumo):
                if _vencido(quem.get("convite_ate", "")):
                    return None
                return c, quem
    return None


def definir_senha(bruto: str, senha: str) -> tuple[Conta, str] | None:
    """Usa o convite para criar a senha. O convite morre aqui."""
    achado = dono_do_convite(bruto)
    if achado is None:
        return None
    conta, quem = achado
    if len(senha or "") < MIN_SENHA:
        raise ContaInvalida(f"a senha precisa de pelo menos {MIN_SENHA} caracteres")
    amassada = _amassar(senha, secrets.token_bytes(16))
    if quem["id"] == DONO:
        conta.senha, conta.convite, conta.convite_ate = amassada, "", ""
    else:
        for p in conta.pessoas:
            if p.get("id") == quem["id"]:
                p["senha"], p["convite"], p["convite_ate"] = amassada, "", ""
    _gravar(conta)
    return conta, quem["id"]


def nascer_da_assinatura(empresa: str, email: str, plano_pedido: str,
                         financeiro: str = "") -> tuple[Conta, str]:
    """A conta que nasce de uma contratação, antes de o pagamento ser aprovado.

    Nasce **sem senha e sem plano**: existe para a cobrança ter dono e para o
    aviso de pagamento ter onde chegar. Quem libera é o aviso do meio de
    pagamento, e é ele que dispara o convite de acesso.
    """
    email = (email or "").strip().lower()
    financeiro = (financeiro or "").strip().lower()
    if not EMAIL.fullmatch(email):
        raise ContaInvalida("e-mail inválido")
    if financeiro and not EMAIL.fullmatch(financeiro):
        raise ContaInvalida("e-mail do financeiro inválido")
    if por_email(email):
        raise ContaInvalida("já existe conta com esse e-mail")
    c = Conta(id=_ident_de(empresa, email), nome=(empresa or "").strip() or email,
              email=email, criada=_agora(), plano="sem", senha="",
              email_financeiro=financeiro, plano_pedido=plano_pedido)
    _gravar(c)
    return c, novo_convite(c, DONO)


# ----------------------------------------------------------------- chaves

def _indice() -> dict:
    f = pasta() / "chaves.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _gravar_indice(d: dict) -> None:
    (pasta() / "chaves.json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                         encoding="utf-8")


def nova_chave(conta: Conta, apelido: str = "") -> str:
    """Sorteia uma chave e devolve o valor em claro — a única vez.

    32 bytes de entropia: não se adivinha, não se enumera. Do lado de cá fica
    só o resumo, então vazar o disco não dá acesso a ninguém.
    """
    chave = PREFIXO_CHAVE + secrets.token_urlsafe(32)
    registro = {"id": secrets.token_hex(4), "apelido": (apelido or "").strip()[:40],
                "criada": _agora(), "fim": "", "resumo": _resumo(chave)}
    conta.chaves.append(registro)
    _gravar(conta)
    indice = _indice()
    indice[registro["resumo"]] = {"conta": conta.id, "chave": registro["id"]}
    _gravar_indice(indice)
    return chave


def revogar(conta: Conta, id_da_chave: str) -> bool:
    achada = next((c for c in conta.chaves if c["id"] == id_da_chave and not c["fim"]),
                  None)
    if achada is None:
        return False
    achada["fim"] = _agora()
    _gravar(conta)
    indice = _indice()
    indice.pop(achada["resumo"], None)
    _gravar_indice(indice)
    return True


def da_chave(chave: str) -> Conta | None:
    """De quem é esta chave. Nenhuma busca por conta: o índice resolve direto."""
    if not chave or not chave.startswith(PREFIXO_CHAVE):
        return None
    achado = _indice().get(_resumo(chave))
    if not achado:
        return None
    c = por_id(achado["conta"])
    if c is None or not c.ativa:
        return None
    registro = next((k for k in c.chaves if k["id"] == achado["chave"]), None)
    if registro is None or registro.get("fim"):
        return None
    return c


# ----------------------------------------------------------------- sessão da tela

SELO_VALE = 60 * 60 * 24 * 14          # duas semanas


def _segredo() -> bytes:
    """O segredo que assina a sessão.

    Sem `REPLICAI_SEGREDO` no ambiente, um é sorteado ao subir — e aí toda
    reinicialização desloga todo mundo. Serve para desenvolver; em produção é
    configurado, senão dois servidores atrás do mesmo endereço não reconhecem
    a sessão um do outro.
    """
    import api.contas as eu
    bruto = os.environ.get("REPLICAI_SEGREDO")
    if bruto:
        return bruto.encode()
    if not getattr(eu, "_SORTEADO", None):
        eu._SORTEADO = secrets.token_bytes(32)
    return eu._SORTEADO


def segredo_configurado() -> bool:
    return bool(os.environ.get("REPLICAI_SEGREDO"))


def selar(conta_id: str, quem: str = "dono") -> str:
    """Um selo de sessão: a conta, a pessoa, até quando, e a assinatura disso.

    A pessoa entra no selo porque é o que permite dizer quem ajustou cada peça
    sem perguntar de novo a cada requisição.
    """
    ate = int(datetime.now(timezone.utc).timestamp()) + SELO_VALE
    corpo = f"{conta_id}:{quem}:{ate}"
    assinatura = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    return f"{corpo}:{assinatura}"


def abrir(selo: str) -> tuple[str, str] | None:
    """Devolve (conta, pessoa) do selo, ou nada."""
    try:
        conta_id, quem, ate, assinatura = (selo or "").rsplit(":", 3)
    except ValueError:
        return None
    esperado = hmac.new(_segredo(), f"{conta_id}:{quem}:{ate}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperado):
        return None
    try:
        if int(ate) < int(datetime.now(timezone.utc).timestamp()):
            return None
    except ValueError:
        return None
    return conta_id, quem


def abrir_selo(selo: str) -> str | None:
    """Devolve a conta do selo, ou nada. Assinatura conferida antes da data:
    selo forjado não merece nem a conta de prazo."""
    aberto = abrir(selo)
    return aberto[0] if aberto else None


