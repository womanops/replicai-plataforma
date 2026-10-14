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
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

    def em_json(self) -> dict:
        """Sem segredo: é isto que pode sair da API."""
        return {"id": self.id, "nome": self.nome, "email": self.email,
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
                    "fontes": c.fontes},
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
    alvo = (email or "").strip().lower()
    return next((c for c in todas() if c.email == alvo), None)


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


def autenticar(email: str, senha: str) -> Conta | None:
    c = por_email(email)
    if c is None:
        # gasta o mesmo tempo de uma conta que existe: responder rápido quando
        # o e-mail não existe conta quais e-mails existem
        _amassar(senha or "", b"0" * 16)
        return None
    if not c.ativa or not conferir_senha(senha or "", c.senha):
        return None
    return c


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


def selar(conta_id: str) -> str:
    """Um selo de sessão: quem é, até quando, e a assinatura disso."""
    ate = int(datetime.now(timezone.utc).timestamp()) + SELO_VALE
    corpo = f"{conta_id}:{ate}"
    assinatura = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    return f"{corpo}:{assinatura}"


def abrir_selo(selo: str) -> str | None:
    """Devolve a conta do selo, ou nada. Assinatura conferida antes da data:
    selo forjado não merece nem a conta de prazo."""
    try:
        conta_id, ate, assinatura = (selo or "").rsplit(":", 2)
    except ValueError:
        return None
    esperado = hmac.new(_segredo(), f"{conta_id}:{ate}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperado):
        return None
    try:
        if int(ate) < int(datetime.now(timezone.utc).timestamp()):
            return None
    except ValueError:
        return None
    return conta_id
