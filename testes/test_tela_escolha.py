"""O que a tela precisa deixar à mão: escolher, acompanhar e ver.

Cada teste aqui nasceu de uma frase da Ligia usando a plataforma, e a ordem
dos elementos na página é parte do produto — "está escondido" é um defeito,
não uma questão de gosto. A tela é um arquivo só, então a verificação é sobre
o texto dela; o que dá para medir sem navegador é a ORDEM e a presença da
regra, e é isso que está aqui.
"""
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def tela():
    return Path("web/index.html").read_text(encoding="utf-8")


def antes(tela, a, b):
    """`a` aparece antes de `b` na página."""
    ia, ib = tela.find(a), tela.find(b)
    assert ia >= 0, f"não achei {a!r}"
    assert ib >= 0, f"não achei {b!r}"
    return ia < ib


class TestOQueFicaNoAlto:
    def test_a_medida_livre_vem_antes_da_grade(self, tela):
        """Ela ficava no pé de uma lista de cinquenta formatos: quem precisa
        de uma medida que não está no catálogo rolava a tela inteira para
        descobrir que dava."""
        assert antes(tela, 'class="livre"', 'id="formatos"')

    def test_os_canais_vem_antes_da_grade(self, tela):
        assert antes(tela, 'id="canais"', 'id="formatos"')

    def test_o_andamento_vem_antes_do_conteudo(self, tela):
        """No rodapé ele é uma tira de 3 px embaixo de tudo, e quem está
        olhando os formatos não vê o pé da tela."""
        assert antes(tela, 'id="andamento"', "<main>")


class TestEscolherPorCanal:
    """"Se eu clicar em instagram, apenas os formatos de instagram aparecem
    selecionados, e eu escolho se mantenho todos ou não; então posso clicar em
    outro pra complementar as escolhas." """

    def test_o_canal_soma_em_vez_de_trocar(self, tela):
        """Complementar: clicar em LinkedIn não pode apagar o Instagram."""
        # a única limpeza é a do botão de limpar, e ela é explícita
        assert "if (!canal){ filtro.length = 0; escolhidos.clear(); }" in tela
        assert tela.count("escolhidos.clear()") == 1

    def test_o_canal_tambem_filtra_o_que_esta_a_vista(self, tela):
        """"Ao clicar num canal, apenas ele fica visível e no topo, como um
        filtro mesmo; conforme vai clicando em outros, aparecem apenas os
        selecionados em vez de ficar aquela lista enorme." """
        assert "const canais = filtro.length ? filtro.filter(c => m[c]) : Object.keys(m);" in tela

    def test_o_filtro_guarda_a_ordem_dos_cliques(self, tela):
        """Quem clicou em LinkedIn depois de Instagram espera o LinkedIn
        embaixo, não no lugar que o catálogo deu a ele."""
        assert "filtro.push(canal)" in tela
        assert "const filtro = [];" in tela

    def test_da_para_voltar_a_ver_tudo(self, tela):
        assert "'ver tudo' : 'limpar'" in tela

    def test_clicar_de_novo_desmarca_so_aquele_canal(self, tela):
        assert "const inteiro = fs.every(f => escolhidos.has(f.id));" in tela
        assert "inteiro ? escolhidos.delete(f.id) : escolhidos.add(f.id)" in tela

    def test_a_ficha_mostra_quantos_daquele_canal_estao_marcados(self, tela):
        """Sem a conta, "parte marcado" e "tudo marcado" ficam iguais."""
        assert "n === fs.length ? ' on' : ' parte'" in tela

    def test_marcar_um_formato_atualiza_a_ficha_do_canal(self, tela):
        assert "pintarCanais(); pintarRodape();" in tela


class TestMedidaGuardada:
    """"Se a pessoa quiser salvar um formato novo manual depois de inserir, dá
    pra gravar no sistema dela? Porque sempre que ela for gerar, se tiver esse
    formato, já fica gravado pra ela." """

    def test_a_tela_carrega_as_medidas_da_conta(self, tela):
        assert "fetch('/eu/medidas')" in tela
        assert "carregarMedidas().then(carregarFormatos);" in tela

    def test_adicionar_guarda_na_conta(self, tela):
        assert "fetch('/eu/medidas', { method: 'POST', body: fd })" in tela

    def test_tirar_tira_da_conta_tambem(self, tela):
        """Tirar "só desta vez" de uma lista que se lembra é promessa que a
        tela não cumpre: na próxima vez ela estaria de volta."""
        assert "method: 'DELETE'" in tela
        assert "Tirar das minhas medidas" in tela

    def test_a_medida_nova_nao_nasce_escondida_atras_do_filtro(self, tela):
        assert "if (filtro.length && !filtro.includes(CANAL_MEU)) filtro.push(CANAL_MEU);" in tela


class TestVerAPecaPronta:
    def test_clicar_na_peca_pronta_amplia(self, tela):
        """Dava para ajustar e não dava para ver: só o botãozinho de canto
        ampliava. Para decidir se quer ajustar, primeiro é preciso enxergar."""
        assert "if (job){ if (vd || im) ampliar((vd || im).src, b.dataset.id, !!vd); return; }" in tela

    def test_a_peca_animada_tambem_amplia(self, tela):
        """O vídeo substituía o conteúdo do cartão e levava junto o botão de
        ampliar: a peça animada ficava sem jeito nenhum de ser vista grande."""
        assert 'ampliar(cx.querySelector(\'video\').src, fid, true)' in tela
        assert "<video hidden autoplay loop muted playsinline controls>" in tela

    def test_da_lupa_para_o_ajuste_sem_fechar(self, tela):
        assert "Ajustar esta peça" in tela


class TestAMargemNaPrancha:
    """"A linha de limite para não cortar texto não fica clara, porque tem
    outras linhas de cada elemento ajustável na peça." """

    def test_a_margem_tem_cor_propria(self, tela):
        """Rosa pontilhado fino no meio de dez caixas era mais uma linha."""
        assert "border:1.5px dashed rgba(255,90,90,.95)" in tela

    def test_o_que_fica_fora_da_margem_escurece(self, tela):
        """A área boa se vê, não se deduz."""
        assert "box-shadow:0 0 0 9999px rgba(8,5,7,.45)" in tela
        # a sombra é recortada por um véu: sem ele, 9999 px escurecem a tela
        # inteira, e `overflow` na lona cortaria os manípulos das bordas
        assert '<div class="veu">' in tela
        assert "#lona .veu{position:absolute;inset:0;overflow:hidden" in tela

    def test_a_margem_se_apresenta(self, tela):
        assert "margem de recorte · nada de texto passa daqui" in tela

    def test_as_caixas_dos_elementos_baixam_o_tom(self, tela):
        """Elas competiam com a margem na mesma espessura e no mesmo brilho."""
        assert ".pe-el{position:absolute;border:1px solid rgba(var(--fgRGB),.22)" in tela
        assert ".pe-el:hover .rot,.pe-el.sel .rot{display:block}" in tela


class TestOAndamento:
    def test_o_alto_repete_o_que_o_rodape_diz(self, tela):
        assert "$('#andEtapa').textContent = $('#conta').textContent;" in tela

    def test_acende_e_apaga_junto_com_o_trabalho(self, tela):
        assert "espelhar(andandoAlgo, f)" in tela
        assert tela.count("espelhar(false)") >= 2

    def test_sem_fracao_a_barra_nao_inventa_porcentagem(self, tela):
        """Na fila, ou abrindo o PSD, não há fração medida: a barra vai e vem
        em vez de mostrar um número que ninguém calculou."""
        assert "a.classList.toggle('sem', !tem)" in tela
        assert "#andamento.sem .trilha i{" in tela


class TestOSaldoNoTopo:
    """O contador do cabeçalho mostrava "usadas/franquia" — o mesmo par de
    números dizendo o contrário do que parece. Quem olha de passagem lê o
    primeiro número como o que ainda tem."""

    def test_mostra_o_que_resta_sobre_a_franquia(self, tela):
        assert "const resta = Math.max(0, u.resta.pecas);" in tela
        assert "<b>${resta}/${u.plano.pecas}</b>" in tela

    def test_diz_que_e_saldo(self, tela):
        assert "saldo de peças" in tela

    def test_o_que_ja_foi_feito_continua_a_mao(self, tela):
        """Some do número, mas não do produto: fica no texto de passar o mouse."""
        assert "Você já fez ${u.pecas} de ${u.plano.pecas} peças" in tela


class TestOAvisoDoCompositor:
    """"Compondo com o modelo" ficava fixo no alto da tela. O normal não é
    notícia; o aviso de verdade — caiu para a régua — é o que precisa ser
    visto, e ruído fixo ao lado dele é o que o faz passar batido."""

    def test_o_normal_nao_escreve_nada(self, tela):
        assert "'compondo com o modelo'" not in tela
        assert "el.textContent = simples ? 'compondo por regra · sem o modelo' : '';" in tela

    def test_a_queda_para_a_regua_continua_aparecendo(self, tela):
        assert "compondo por regra · sem o modelo" in tela
        assert "ANTHROPIC_API_KEY não foi lida" in tela


class TestAEscolhaDaPrancheta:
    """"Quando subi o PSD ele perguntou qual deles era, mas veio uma prévia
    que nem dava pra enxergar." A miniatura embutida no PSD tem 256 px para o
    documento INTEIRO: recortada numa prancheta, vira um borrão."""

    def test_a_previa_composta_entra_no_lugar_do_borrao(self, tela):
        assert "async function trocarPorPrevias()" in tela
        assert "cx.innerHTML = `<img src=\"/jobs/${job}/arquivos/" in tela

    def test_a_lista_nao_espera_a_previa(self, tela):
        """A lista aparece na hora; as imagens chegam atrás, uma por uma."""
        assert "$('#pranchetas').classList.remove('hidden');\n  trocarPorPrevias();" in tela

    def test_para_de_olhar_quando_a_escolha_foi_feita(self, tela):
        assert tela.count("clearInterval(olhoNaPrancheta)") >= 2

    def test_o_cartao_cabe_a_leitura(self, tela):
        assert "minmax(300px,1fr)" in tela


class TestARessalvaSeLe:
    """O aviso morava no `title` do selo: texto que só aparece se a pessoa
    parar o mouse em cima e esperar, numa linha só. Aviso que precisa de
    insistência para aparecer é aviso que não foi dado."""

    def test_a_ressalva_abre_uma_folha(self, tela):
        assert "function verRessalvas(fid, avisos, fora)" in tela
        assert 'id="ressalvas"' in tela

    def test_a_folha_mostra_o_que_ficou_de_fora(self, tela):
        """`descartados` é a explicação do modelo para cada coisa que não
        entrou — era gravada e nunca mostrada."""
        assert "Object.entries(fora || {})" in tela
        assert "(d.descartados || {})[id]" in tela

    def test_o_selo_convida_o_clique(self, tela):
        assert "cursor:pointer;text-decoration:underline" in tela


class TestAjustarTextoEElemento:
    """"Ao clicar em cima de um elemento, aparece uma lixeira, caso a pessoa
    deseje eliminar o item" — e o modo passou a prometer ajustar os TEXTOS de
    cada peça, então ele tem que entregar isso."""

    def test_a_lixeira_aparece_no_elemento_escolhido(self, tela):
        """Delete continua valendo, mas ninguém descobre tecla."""
        assert 'class="lixo" type="button" title="Tirar da peça"' in tela
        assert "function tirarDaPeca(g)" in tela

    def test_so_o_escolhido_tem_lixeira(self, tela):
        """Uma por caixa, em dez caixas, é um campo minado sobre a peça."""
        assert "ed.sel === g.chave" in tela

    def test_o_lapis_troca_o_texto(self, tela):
        assert "function trocarTexto(g)" in tela
        assert 'class="lapis"' in tela

    def test_a_troca_diz_qual_e_a_fonte_da_arte(self, tela):
        """O PSD sabe que a linha é FuturaICG-Bold. Trocar o texto sem dizer
        isso é trocar a letra junto, calado."""
        assert "fonte da arte: ${fonte}" in tela

    def test_quando_falta_a_fonte_a_tela_pede_o_arquivo(self, tela):
        """Sem o arquivo o texto sai na letra da casa. O lugar de resolver é
        aqui, no instante em que a pessoa está trocando."""
        assert "function pedirFonte(familia)" in tela
        assert "fetch('/eu/fontes', { method: 'POST', body: fd })" in tela
        assert "na mesma letra" in tela

    def test_a_fonte_guardada_vale_para_os_proximos_trabalhos(self, tela):
        assert "async function carregarFontes()" in tela
        assert "carregarFontes();" in tela

    def test_a_linha_trocada_volta_como_um_elemento_so(self, tela):
        assert "tipografar: true" in tela
        assert "g.itens.slice(1).forEach(i => sumiu.add(i));" in tela

    def test_desfazer_tudo_desfaz_a_troca_tambem(self, tela):
        assert "ed.fora.clear(); ed.trocas = {}; ed.sel = null; pintarLona();" in tela

    def test_o_modo_diz_o_que_ele_faz(self, tela):
        assert "Adaptação + Ajustes" in tela
        assert "ajustar a diagramação e os textos de cada" in tela


class TestASelecaoSolta:
    """"Ajustamos, clicamos fora da imagem e ela precisa sair do select, senão
    fica tudo selecionado." O elemento escolhido sobe de camada para o manípulo
    dele ficar alcançável — e, sem soltar, ele passa a roubar o clique do
    vizinho inteiro."""

    def test_clicar_no_vazio_da_prancha_solta(self, tela):
        assert "lona.onpointerdown = ev => {" in tela
        assert "if (ev.target.closest('.pe-el') || ed.sel === null) return;" in tela

    def test_clicar_fora_da_prancha_tambem(self, tela):
        """A prancha é menor que a tela: o escuro em volta é o lugar mais
        natural de dizer "nenhum"."""
        assert "if (!ev.target.closest('#palco')) return;" in tela


class TestFontesDaMarcaNaTela:
    def test_da_para_enviar_a_fonte_junto_da_arte(self, tela):
        """Sem isso o único caminho era topar com o aviso no meio de um
        ajuste."""
        assert 'id="fontes"' in tela
        assert "Fontes da marca" in tela
        assert "$('#btnFonte').onclick" in tela

    def test_o_painel_fica_do_lado_da_arte(self, tela):
        assert antes(tela, 'id="zona"', 'id="fontes"')
        assert antes(tela, 'id="fontes"', 'id="formatos"')

    def test_a_lista_mostra_e_tira_o_que_ja_foi_enviado(self, tela):
        assert "function pintarFontes()" in tela
        assert "'/eu/fontes/' + encodeURIComponent(id), { method: 'DELETE' }" in tela

    def test_o_campo_de_fora_nao_e_o_do_editor(self, tela):
        """`click()` num input dentro de `display:none` não abre nada."""
        assert "const campo = $('#fonteArquivo2');" in tela
