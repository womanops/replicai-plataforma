"""As ferramentas da tela de ajuste, medidas no navegador de verdade.

Em 24/10/2026 a Ligia disse: "a ferramenta de corte não está mais aqui". Ela
estava — e funcionava. O que ela não estava era ao alcance do olho: a única
porta de entrada do corte era a ÚLTIMA linha da lista de camadas, e num PSD
de dezessete camadas isso fica mil pixels abaixo da dobra, dentro de uma
coluna que rola. Ferramenta fora do campo de visão é ferramenta que não
existe, e nenhum teste pegava isso porque os testes da tela liam o HTML como
texto: a linha `data-chave="__fundo"` estava lá, bonita, no arquivo.

Ler o arquivo responde "a regra está escrita?". Só o navegador responde "dá
para alcançar?" — e é essa a pergunta que ela faz quando usa a plataforma.

Por isso aqui a página é aberta de verdade, com uma peça de muitas camadas, e
o que se mede é geometria: o botão está na tela sem rolar nada, ele acende o
modo de corte, a moldura aparece com os quatro cantos de puxar.
"""
import json
import re

import pytest

from motor.replica import chrome_run, find_chrome

pytestmark = pytest.mark.lento

# A fonte do Google trava o Chrome sem tela: ele fica esperando a rede e
# estoura o tempo. A tela não é testada pela letra dela.
DE_FORA = re.compile(r'<link[^>]+fonts\.(googleapis|gstatic)\.com[^>]*>')

# dezessete camadas: é o tamanho de um PSD de verdade, e é o que empurra a
# lista para baixo da dobra
AFERIR = """
<script>
addEventListener('load', () => {
  const n = 17, els = [];
  for (let i = 0; i < n; i++)
    els.push({ tipo: i % 4 === 0 ? 'texto' : 'imagem',
               papel: i % 4 === 0 ? 'apoio' : 'figura',
               camada: 'Camada ' + (i + 1),
               texto: i % 4 === 0 ? 'Linha ' + i : undefined,
               box: { x: 40 + i * 8, y: 40 + i * 20, w: 300, h: 60 } });
  ed = { fid: 'prova', peca: { canvas: { w: 1080, h: 1080 },
           safe: { left: 40, right: 40, top: 40, bottom: 40 },
           elementos: els, fundo: {}, versao: 1 },
         k: 1, sel: null, trocas: {},
         boxes: els.map(e => ({...e.box})), orig: els.map(e => ({...e.box})),
         letras: els.map(() => null), letrasOrig: els.map(() => null),
         recorte: null, recorteMexido: false, versao: 1,
         fora: new Set(), passos: [], ultimo: null };
  document.getElementById('editor').classList.remove('hidden');
  pintarLona();

  const naTela = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0
        && r.top >= 0 && r.bottom <= innerHeight
        && r.left >= 0 && r.right <= innerWidth;
  };
  const corta = document.getElementById('edCorta');
  const medido = {
    camadas: document.querySelectorAll('#edCamadas button').length,
    temBotaoDeCorte: !!corta,
    cortaNaTela: naTela(corta),
    // a linha da lista continua existindo; o que ela NÃO pode ser é o único
    // caminho, e é isso que este número denuncia
    linhaDaListaNaTela: naTela(document.querySelector('#edCamadas [data-chave="__fundo"]')),
    desfazNaTela: naTela(document.getElementById('edDesfaz')),
  };
  if (corta){
    corta.click();
    const m = document.querySelector('#lona .corte');
    medido.molduraDepoisDoClique = !!m;
    medido.cantosDePuxar = m ? m.querySelectorAll('.pc').length : 0;
    medido.acendeu = corta.getAttribute('aria-pressed');
    corta.click();
    medido.desligaNoSegundoClique = !document.querySelector('#lona .corte');
  }

  // o resto do que ela já aprovou nesta tela, medido na mesma abertura:
  // cada um destes nasceu de uma frase dela, e todos moram no mesmo lugar
  ed.sel = null; pintarLona();
  medido.temGrade = !!document.querySelector('#lona .reguas');
  medido.temMargem = !!document.querySelector('#lona .margem');
  const primeiro = document.querySelector('#edCamadas button[data-chave]');
  if (primeiro){
    primeiro.click();
    const escolhido = document.querySelector('.pe-el.sel');
    medido.botoesSoNoEscolhido = document.querySelectorAll('.pe-el .lixo').length;
    medido.tirarDiz = escolhido ? (escolhido.querySelector('.lixo') || {}).textContent : null;
    medido.temManipulo = !!(escolhido && escolhido.querySelector('.puxa'));
  }

  const saida = document.createElement('pre');
  saida.id = 'aferido';
  saida.textContent = JSON.stringify(medido);
  document.body.appendChild(saida);
});
</script>
"""


@pytest.fixture(scope="module")
def medido(tmp_path_factory):
    if not find_chrome():
        pytest.skip("Chrome não instalado")
    from pathlib import Path
    tela = Path("web/index.html").read_text(encoding="utf-8")
    # a página não fecha <body>: o aferidor vai no fim do arquivo mesmo
    tela = DE_FORA.sub("", tela) + AFERIR
    p = tmp_path_factory.mktemp("tela") / "index.html"
    p.write_text(tela, encoding="utf-8")
    r = chrome_run(f"file://{p}", ["--dump-dom", "--window-size=1440,900"], timeout=90)
    achado = re.search(r'<pre id="aferido">(.*?)</pre>', r.stdout, re.S)
    assert achado, "a tela não chegou a abrir o editor no navegador"
    return json.loads(achado.group(1))


class TestAFerramentaDeCorte:
    def test_a_peca_de_prova_tem_camadas_demais_para_caber(self, medido):
        """Se a lista couber na tela, o teste abaixo passa à toa."""
        assert medido["camadas"] >= 18
        assert not medido["linhaDaListaNaTela"], (
            "a lista coube inteira na tela: esta prova precisa de uma peça "
            "com mais camadas para valer alguma coisa")

    def test_o_botao_de_cortar_esta_a_vista_sem_rolar(self, medido):
        assert medido["temBotaoDeCorte"], "não há botão de cortar na barra do editor"
        assert medido["cortaNaTela"], (
            "a ferramenta de corte só é alcançável rolando a lista de camadas")

    def test_o_botao_acende_e_abre_a_moldura(self, medido):
        assert medido.get("molduraDepoisDoClique"), "cliquei em cortar e nada apareceu"
        assert medido.get("acendeu") == "true"
        assert medido.get("cantosDePuxar") == 4

    def test_clicar_de_novo_desliga(self, medido):
        assert medido.get("desligaNoSegundoClique")


class TestOQueMaisNaoPodeSumirDaBarra:
    def test_o_desfazer_esta_a_vista(self, medido):
        """Pedido dela em 18/10: "deveríamos ter um botão com uma seta para
        desfazer alguma ação feita"."""
        assert medido["desfazNaTela"]


class TestOQueElaJaAprovouNestaTela:
    """Cada um destes foi pedido, feito e aprovado uma vez. A lista existe
    para que não precise ser pedida duas."""

    def test_a_grade_de_alinhamento_esta_na_lona(self, medido):
        """18/10: "o grid que pedi para medir a régua não tem"."""
        assert medido["temGrade"]

    def test_a_margem_de_recorte_tambem(self, medido):
        assert medido["temMargem"]

    def test_tirar_da_peca_e_um_x_e_nao_uma_lixeira(self, medido):
        """18/10: "a latinha de lixo, por exemplo é enorme, ela poderia ser
        um X"."""
        assert medido["tirarDiz"] == "✕"

    def test_o_manipulo_so_aparece_no_elemento_escolhido(self, medido):
        """Pintado em toda caixa, virava uma peneira de pontos vermelhos — e
        tapava justamente a ponta do elemento que ela quer ver para esticar."""
        assert medido["temManipulo"]
        assert medido["botoesSoNoEscolhido"] == 1
