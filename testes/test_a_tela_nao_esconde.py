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
         fora: new Set(), juntas: new Set(), pilha: null, zoom: 1,
         passos: [], ultimo: null };
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

  // OS GESTOS DO PHOTOSHOP. Cada um foi pedido por ela em 26/10/2026, e cada
  // um é geometria — ou a proporção se mantém, ou não se mantém.
  Element.prototype.setPointerCapture = function(){};
  const arrasta = (alvo, dx, dy, mais) => {
    const r = alvo.getBoundingClientRect();
    const b = { bubbles: true, pointerId: 1, clientX: r.left + r.width / 2,
                clientY: r.top + r.height / 2, ...(mais || {}) };
    alvo.dispatchEvent(new PointerEvent('pointerdown', b));
    window.dispatchEvent(new PointerEvent('pointermove',
      { ...b, clientX: b.clientX + dx, clientY: b.clientY + dy }));
    window.dispatchEvent(new PointerEvent('pointerup', b));
  };
  const chaves = grupos().map(g => g.chave);
  const prop = b => Math.round((b.w / b.h) * 1000) / 1000;

  escolher(chaves[0]); pintarLona();
  const i0 = grupos()[0].itens[0];
  const caixa0 = { ...ed.boxes[i0] };
  const puxa = document.querySelector('.pe-el .puxa');
  medido.temManipuloParaEscalar = !!puxa;
  if (puxa){
    arrasta(puxa, 90, 6);
    medido.cresceu = ed.boxes[i0].w > caixa0.w;
    medido.proporcaoAntes = prop(caixa0);
    medido.proporcaoDepois = prop(ed.boxes[i0]);
    ed.boxes[i0] = { ...caixa0 }; pintarLona();
    arrasta(document.querySelector('.pe-el .puxa'), 90, 6, { shiftKey: true });
    medido.proporcaoComShift = prop(ed.boxes[i0]);
  }

  const botao = c => [...document.querySelectorAll('#edCamadas button[data-chave]')]
    .find(b => b.dataset.chave === c);
  ed.boxes = ed.orig.map(b => ({ ...b })); escolher(null); pintarLona();
  botao(chaves[0]).dispatchEvent(new MouseEvent('click', { bubbles: true }));
  botao(chaves[1]).dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
  medido.escolhidasComShift = ed.juntas.size;
  const conjunto = document.querySelector('.pe-juntas');
  medido.temCaixaDeConjunto = !!conjunto;
  if (conjunto){
    const i1 = grupos().find(g => g.chave === chaves[0]).itens[0];
    const i2 = grupos().find(g => g.chave === chaves[1]).itens[0];
    const x1 = ed.boxes[i1].x, x2 = ed.boxes[i2].x;
    arrasta(conjunto, 40, 0);
    medido.andouJunto = (ed.boxes[i1].x - x1) === (ed.boxes[i2].x - x2)
                        && ed.boxes[i1].x !== x1;
  }

  // a lista é de cima para baixo, como a do Photoshop
  const naLista = [...document.querySelectorAll('#edCamadas button[data-chave]')]
    .map(b => b.dataset.chave).filter(c => c !== '__fundo');
  medido.listaDeCimaParaBaixo = naLista.join('|') === chaves.slice().reverse().join('|');
  medido.fundoNoPe = [...document.querySelectorAll('#edCamadas button[data-chave]')]
    .pop().dataset.chave === '__fundo';

  // empilhar com a tecla de comando, e o conjunto sobe rígido
  escolher(null); ed.pilha = null; pintarLona();
  botao(chaves[0]).dispatchEvent(new MouseEvent('click', { bubbles: true }));
  const pilhaAntes = grupos().map(g => g.chave).join('|');
  empilhar(1);
  medido.subiuNaPilha = grupos().map(g => g.chave).join('|') !== pilhaAntes;

  // o zoom
  ed.zoom = 1; pintarLona();
  const kCabe = ed.k;
  aproximar(1.25);
  medido.zoomCresceu = ed.k > kCabe;
  medido.zoomDiz = /%/.test(document.getElementById('edMedida').textContent);
  for (let n = 0; n < 30; n++) aproximar(1.25);
  medido.zoomTemTeto = ed.zoom <= 6;
  ed.zoom = 1; pintarLona();

  // O MENOR SOB O CURSOR. A foto grande fica ACIMA do texto pequeno na pilha
  // — então a caixa dela cobre a dele. O clique tem que achar o texto assim
  // mesmo, senão a camada de baixo vira inalcançável na prancheta.
  const grande = chaves[0], pequeno = chaves[1];
  const ig = grupos().find(g => g.chave === grande).itens[0];
  const ip = grupos().find(g => g.chave === pequeno).itens[0];
  ed.boxes[ig] = { x: 0, y: 0, w: 900, h: 1400 };
  ed.boxes[ip] = { x: 300, y: 500, w: 200, h: 80 };
  ed.pilha = chaves.filter(c => c !== grande).concat([grande]);   // a foto no topo
  escolher(null); pintarLona();
  const caixaG = document.querySelector(`.pe-el[data-chave="${CSS.escape(grande)}"]`);
  const caixaP = document.querySelector(`.pe-el[data-chave="${CSS.escape(pequeno)}"]`);
  medido.oGrandeDesenhaPorCima =
    Number(getComputedStyle(caixaG).zIndex) > Number(getComputedStyle(caixaP).zIndex);
  const rp = caixaP.getBoundingClientRect();
  caixaG.dispatchEvent(new PointerEvent('pointerdown', {
    bubbles: true, pointerId: 1,
    clientX: rp.left + rp.width / 2, clientY: rp.top + rp.height / 2 }));
  window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 }));
  medido.cliqueAchouOMenor = ed.sel === pequeno;

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


class TestOsGestosDoPhotoshop:
    """Pedido dela em 26/10/2026: "preciso que os comandos da tela de ajustes
    sejam iguais aos do photoshop". Cada teste aqui é um dos gestos, medido
    no navegador — proporção é número, não impressão."""

    def test_puxar_o_canto_mantem_a_proporcao(self, medido):
        assert medido["temManipuloParaEscalar"]
        assert medido["cresceu"], "puxar o canto não aumentou a camada"
        assert medido["proporcaoDepois"] == medido["proporcaoAntes"], (
            "a imagem saiu distorcida: a proporção mudou de "
            f"{medido['proporcaoAntes']} para {medido['proporcaoDepois']}")

    def test_com_shift_a_deformacao_e_liberada(self, medido):
        """Como no Photoshop desde 2019: proporcional por padrão, livre com
        Shift. Sem esta saída não há como achatar de propósito."""
        assert medido["proporcaoComShift"] != medido["proporcaoAntes"]

    def test_shift_no_clique_escolhe_varias(self, medido):
        assert medido["escolhidasComShift"] == 2

    def test_as_escolhidas_andam_juntas_por_uma_moldura_so(self, medido):
        assert medido["temCaixaDeConjunto"], (
            "cada camada ficou com o manípulo dela: puxar um deles cresceria "
            "só aquela, que é o trabalho uma-a-uma que a seleção evita")
        assert medido["andouJunto"], "as camadas escolhidas não andaram juntas"

    def test_a_lista_de_camadas_e_de_cima_para_baixo(self, medido):
        """A de cima na lista é a que cobre as outras, e o Fundo fica no pé —
        como no Photoshop. Ao contrário, arrastar para reordenar significa o
        oposto do que a mão espera."""
        assert medido["listaDeCimaParaBaixo"]
        assert medido["fundoNoPe"]

    def test_da_para_mudar_o_empilhamento(self, medido):
        assert medido["subiuNaPilha"]


class TestOZoomDaPrancheta:
    """Numa peça de 1080x1920 vista a 40% da tela, um pixel de arrasto são
    dois e meio da peça: não há como encostar na margem com precisão."""

    def test_aproximar_aumenta_de_verdade(self, medido):
        assert medido["zoomCresceu"]

    def test_a_tela_diz_em_quanto_esta(self, medido):
        assert medido["zoomDiz"], "aproximou e não disse de quanto"

    def test_o_zoom_tem_teto(self, medido):
        assert medido["zoomTemTeto"]


class TestOQueSeVeEOQueSePega:
    """O empilhamento da tela passou a ser o de verdade — o que se vê é o que
    a peça vai ser. Isso devolveu um problema antigo dela: a caixa da foto
    cobre a da linha de texto e rouba o clique.

    As duas coisas convivem separadas: o DESENHO empilha pela ordem do
    arquivo, o CLIQUE procura a caixa de menor área sob o cursor.
    """

    def test_a_camada_de_cima_desenha_por_cima(self, medido):
        assert medido["oGrandeDesenhaPorCima"], (
            "a tela empilhou ao contrário do que a peça vai sair")

    def test_mas_o_clique_acha_a_camada_de_baixo(self, medido):
        assert medido["cliqueAchouOMenor"], (
            "cliquei em cima do texto e a foto que o cobre foi selecionada: "
            "a camada de baixo ficou inalcançável na prancheta")
