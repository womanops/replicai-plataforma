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
        # a única limpeza do atalho de canal é a do botão de limpar, e ela é
        # explícita. Fora dele há outra, em `reabrir`, que troca a escolha
        # pela da campanha que está sendo aberta — essa é outra história
        assert "else if (!canal){ filtro.length = 0; escolhidos.clear(); }" in tela
        atalho = tela.split("function pintarCanais(){")[1].split("function pintarFormatos(")[0]
        assert atalho.count("escolhidos.clear()") == 1

    def test_a_grade_nasce_fechada(self, tela):
        """"Nenhuma lista de formatos fica aberta como padrão: ela aparece
        conforme o usuário clica nos canais." Cinquenta retângulos na cara de
        quem ainda vai decidir onde a peça roda é lista que ninguém lê."""
        assert "? filtro.filter(c => m[c])" in tela
        assert "Escolha um canal acima para " in tela

    def test_com_trabalho_na_tela_a_grade_mostra_o_que_foi_pedido(self, tela):
        """A mesma grade vira o resultado. Fechada ali, a pessoa encomendaria
        vinte peças e ficaria olhando para o nada."""
        assert "const canais = escolhendo()" in tela
        assert "(m[c] || []).some(f => escolhidos.has(f.id))" in tela

    def test_o_filtro_guarda_a_ordem_dos_cliques(self, tela):
        """Quem clicou em LinkedIn depois de Instagram espera o LinkedIn
        embaixo, não no lugar que o catálogo deu a ele."""
        assert "filtro.push(canal)" in tela
        assert "const filtro = [];" in tela

    def test_ver_tudo_abre_e_limpar_fecha(self, tela):
        """Eram o mesmo botão quando a grade nascia aberta, e aí "ver tudo"
        queria dizer "fechar o filtro" — o contrário do que está escrito."""
        assert 'data-canal="*">ver tudo' in tela
        assert "filtro.push(...Object.keys(porCanal()))" in tela
        assert 'data-canal="">limpar' in tela

    def test_a_medida_livre_abre_o_canal_dela(self, tela):
        """A grade fechada esconderia a medida que a pessoa acabou de guardar."""
        assert "if (!filtro.includes(CANAL_MEU)) filtro.push(CANAL_MEU);" in tela

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

    def test_a_medida_nova_nao_nasce_escondida(self, tela):
        """Com a grade nascendo fechada, guardar uma medida sem abrir o canal
        dela seria guardar no escuro."""
        assert "if (!filtro.includes(CANAL_MEU)) filtro.push(CANAL_MEU);" in tela


class TestVerAPecaPronta:
    def test_clicar_na_peca_pronta_amplia(self, tela):
        """Dava para ajustar e não dava para ver: só o botãozinho de canto
        ampliava. Para decidir se quer ajustar, primeiro é preciso enxergar."""
        assert ("if (!escolhendo()){ if (vd || im) ampliar((vd || im).src, "
                "b.dataset.id, !!vd); return; }") in tela

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
        assert "function verRessalvas(fid)" in tela
        assert 'id="ressalvas"' in tela

    def test_a_folha_mostra_o_que_ficou_de_fora(self, tela):
        """`descartados` é a explicação do modelo para cada coisa que não
        entrou — era gravada e nunca mostrada."""
        assert "Object.entries(fora || {})" in tela
        assert "descartadosDoJob = d.descartados || {}" in tela

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

    def test_o_lapis_leva_ao_campo_do_painel(self, tela):
        """Antes abria a caixinha de digitar do navegador, que esconde a peça
        e não deixa ver o resultado enquanto se escreve."""
        assert "function trocarTexto(g)" in tela
        assert 'class="lapis"' in tela
        assert "campo.focus(); campo.select();" in tela
        assert "prompt(" not in tela.split("function trocarTexto")[1][:400]

    def test_a_troca_diz_qual_e_a_fonte_da_arte(self, tela):
        """O PSD sabe que a linha é FuturaICG-Bold. Trocar o texto sem dizer
        isso é trocar a letra junto, calado. O aviso mora no painel, ao lado
        do campo onde se escreve."""
        assert "Fonte da arte: <b>${fonte}</b>" in tela
        assert "o texto novo sai na letra da casa" in tela

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


class TestOPainelDoAjuste:
    """A prancha mostrava caixas sem nome: o que cada uma é só aparecia
    passando o mouse, e reescrever um texto era por uma caixinha do navegador.
    O painel lateral — lista de camadas e campo de texto — veio do protótipo
    que a Ligia aprovou (ReplicAI LP v7)."""

    def test_tem_lista_de_camadas(self, tela):
        assert 'id="edCamadas"' in tela
        assert "function pintarPainel()" in tela

    def test_a_camada_tem_nome_de_gente(self, tela):
        """"headline" não é nome, e `Consigaz-Nino-Poses-Pose-5-A3-300dpi
        copiar` é o nome do arquivo, não o da coisa."""
        assert "const PAPEIS = { headline: 'Título'" in tela
        assert "function nomeDaCamada(g)" in tela

    def test_o_texto_se_escreve_no_painel(self, tela):
        assert 'id="edTexto"' in tela
        assert "ed.trocas[atual.chave] = campo.value" in tela

    def test_a_camada_de_imagem_diz_que_nao_se_reescreve(self, tela):
        assert "Esta camada é imagem" in tela

    def test_clicar_na_lista_seleciona_na_peca(self, tela):
        assert "ed.sel = b.dataset.chave; pintarLona();" in tela

    def test_as_setas_movem_a_camada_escolhida(self, tela):
        """Arrastar serve para a intenção; para encostar na margem sem passar
        dela, o olho não basta."""
        assert "const passo = e.shiftKey ? 10 : 1;" in tela
        assert "ArrowLeft:[-passo,0]" in tela

    def test_a_seta_nao_rouba_a_tecla_de_quem_digita(self, tela):
        assert tela.count("e.target.tagName === 'INPUT'") >= 2

    def test_o_fundo_aparece_na_lista_como_fixo(self, tela):
        """Ele está na peça e não se move: omitir faz procurar o que não há."""
        assert "<b>Fundo</b><small>fixo</small>" in tela


class TestAFonteQueEstaArtePede:
    """Cada PSD é de um cliente e pede a fonte dele. Mostrar "fontes da marca"
    como uma lista genérica não responde a pergunta que importa: falta alguma
    para ESTA arte?"""

    def test_a_tela_diz_o_que_a_arte_pede(self, tela):
        assert "function pintarFontesPedidas(pedidas)" in tela
        assert "Esta arte pede: " in tela

    def test_separa_a_que_ja_foi_enviada_da_que_falta(self, tela):
        assert "'· enviada' : '· falta'" in tela or "· enviada" in tela
        assert ".fontes .pedidas .falta{color:var(--err)}" in tela

    def test_a_lista_vem_do_que_o_psd_pediu(self, tela):
        """Não é digitada por ninguém: sai da leitura do arquivo."""
        assert "(d.psd || {}).fontes || []" in tela

    def test_o_servidor_guarda_a_fonte_de_cada_camada_de_texto(self):
        import inspect

        from api import pipeline
        fonte = inspect.getsource(pipeline._psd_e_render)
        assert '"fontes": sorted({c.fonte for c in leitura.camadas if c.fonte})' in fonte


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


class TestAFichaDaConta:
    """"Minhas campanhas" era um botão perdido no cabeçalho, ao lado de um
    número de saldo e de um "sair". E as fontes da marca — que são da CONTA —
    moravam no meio do formulário de um trabalho. A ficha junta o que é da
    conta na ordem em que se pergunta: quem sou eu aqui, quanto me resta, com
    que letra eu escrevo, o que já é meu."""

    def test_o_cabecalho_mostra_o_nome_da_empresa(self, tela):
        """É como ela se reconhece — e é a porta da ficha."""
        assert 'id="contaNome"' in tela
        assert "$('#contaNome').textContent = nome;" in tela

    def test_a_ficha_responde_na_ordem_em_que_se_pergunta(self, tela):
        """Quem sou eu aqui, quanto me resta, o que já é meu."""
        assert antes(tela, 'id="fichaNome"', 'id="fichaPlano"')
        assert antes(tela, 'id="fichaPlano"', 'id="listaTrabalhos"')

    def test_o_saldo_aparece_como_o_que_RESTA(self, tela):
        assert "restam <b>${resta}</b> ${oque}" in tela
        assert "de ${total} no ciclo" in tela

    def test_a_ficha_diz_o_ciclo_em_portugues(self, tela):
        """Franquia sem data de virada é número solto — e "2026-10-01 a
        2026-10-31" é o jeito do servidor falar, não o nosso."""
        assert "ciclo de ${diaMes(u.mes)}" in tela
        assert "function diaMes(periodo)" in tela
        assert "de ${meses[a.m]}" in tela

    def test_o_atraso_aparece_onde_se_olha_o_plano(self, tela):
        assert "pagamento em atraso" in tela

    def test_as_fontes_ficam_no_fluxo_do_upload(self, tela):
        """Eu as tinha levado para a ficha, por serem guardadas na conta. A
        Ligia corrigiu: o que manda não é onde ficam guardadas, é de quem é a
        arte. "Cada arte é de um cliente com uma fonte diferente" — então o
        lugar de mandar a fonte é ao lado da arte que a pede."""
        ficha = tela.split('id="minhaConta"')[1].split('id="ressalvas"')[0]
        trabalho = tela.split("<main>")[1].split("</main>")[0]
        assert 'id="listaFontes"' in trabalho
        assert "listaFontes" not in ficha

    def test_de_la_se_sai_e_se_veem_os_planos(self, tela):
        assert "$('#fichaSair').onclick = sair;" in tela
        assert "$('#fichaPlanos').onclick" in tela

    def test_da_para_enviar_a_fonte(self, tela):
        assert "Fontes da marca" in tela
        assert "$('#btnFonte').onclick" in tela

    def test_a_lista_mostra_e_tira_o_que_ja_foi_enviado(self, tela):
        assert "function pintarFontes()" in tela
        assert "'/eu/fontes/' + encodeURIComponent(id), { method: 'DELETE' }" in tela

    def test_o_campo_de_fora_nao_e_o_do_editor(self, tela):
        """`click()` num input dentro de `display:none` não abre nada."""
        assert "const campo = $('#fonteArquivo2');" in tela


class TestAsCampanhasDeAntes:
    """"Gero as peças da campanha X, amanhã da Y, e depois de amanhã quero
    baixar tudo da X de novo — onde eu acho?"

    A API guardava a lista desde sempre e a tela nunca a pedia: fechar a aba
    era perder o caminho de volta, com as peças inteiras no disco.
    """

    def test_a_tela_pede_a_lista_ao_servidor(self, tela):
        assert "fetch('/jobs')" in tela
        assert "async function abrirCampanhas()" in tela

    def test_a_porta_de_entrada_e_a_ficha_da_conta(self, tela):
        """Era um botão em letra miúda no cabeçalho, entre um número de saldo
        e um "sair". Campanha é o que a conta TEM: o lugar dela é na ficha."""
        assert 'id="btnConta"' in tela
        assert "$('#btnConta').onclick = abrirConta;" in tela
        assert "abrirCampanhas();" in tela.split("async function abrirConta()")[1][:600]

    def test_abrir_uma_campanha_traz_as_pecas_de_volta(self, tela):
        """Não é só listar: clicar reabre o trabalho na tela, com os cartões
        dos formatos dele e os botões de baixar."""
        assert "async function reabrir(ident)" in tela
        assert "(d.formatos || []).forEach(f => escolhidos.add(f));" in tela
        assert "acompanhar();" in tela

    def test_a_medida_livre_da_campanha_volta_com_ela(self, tela):
        """Formato fora do catálogo não tem cartão na grade: sem recriá-lo, a
        peça daquela campanha não teria onde aparecer."""
        trecho = tela.split("async function reabrir(ident)")[1][:900]
        assert "livre-" in trecho and "canal: CANAL_MEU" in trecho

    def test_lista_vazia_explica_em_vez_de_ficar_em_branco(self, tela):
        assert "Nenhuma campanha ainda" in tela

    def test_a_data_se_le_em_portugues(self, tela):
        """"2026-10-13T18:02:41+00:00" não é resposta para "quando foi isso"."""
        assert "function quando(iso)" in tela
        assert "'hoje'" in tela or "`hoje ${hora}`" in tela


class TestAOrdemDaTela:
    """O nome da campanha ficava no fim do formulário, embora seja por ele que
    o trabalho é procurado depois. Subiu para junto da arte.

    Eu também tinha levado o modo para DEPOIS da grade, com o argumento de que
    ele só faz sentido sabendo os formatos. A Ligia derrubou: o modo não
    depende dos formatos, depende da ARTE — e mandar rolar cinquenta formatos
    para dizer o que a máquina pode fazer com a peça é o contrário de ajudar.
    O argumento era bonito e errado.
    """

    def test_o_nome_da_campanha_vem_junto_da_arte(self, tela):
        assert antes(tela, 'id="zona"', 'id="titulo"')
        assert antes(tela, 'id="titulo"', 'class="modos"')

    def test_o_modo_fica_com_a_arte_e_nao_depois_da_grade(self, tela):
        assert antes(tela, 'class="modos"', 'id="formatos"')

    def test_os_textos_novos_ficam_colados_no_modo_que_os_pede(self, tela):
        assert antes(tela, 'class="modos"', 'id="campoHead"')

    def test_o_muro_de_tres_paragrafos_virou_um(self, tela):
        """Três explicações abertas no alto da coluna é um muro; quem já sabe
        o que quer relê o mesmo texto toda vez."""
        assert "label.modo small{display:none" in tela
        assert "label.modo.on small{display:block}" in tela


class TestOCartaoMostraOCorte:
    """O cartão vazio era um xadrez cinza: ele dizia a proporção e mais nada.
    Com a arte-mãe apagada dentro dele, a escolha de formato vira prévia — dá
    para ver o que cada enquadramento vai cortar antes de gastar a rodada."""

    def test_o_cartao_leva_a_arte_apagada(self, tela):
        assert 'class="fantasma"' in tela
        assert ".f .cx .fantasma{opacity:" in tela

    def test_so_enquanto_a_peca_nao_saiu(self, tela):
        """Depois de pronta, quem manda no cartão é a peça de verdade: ela
        entra por cima do fantasma, e a guarda do desenho sabe diferenciar os
        dois."""
        assert "cx.querySelector('img:not(.fantasma), video')" in tela
        assert "const fantasma = fonteDoFantasma()" in tela

    def test_o_escolhido_mostra_mais(self, tela):
        assert ".f.on .cx .fantasma{opacity:" in tela


class TestORodapeTemUmDestaque:
    """Depois da entrega o rodapé virava um balcão de cinco botões do mesmo
    tamanho. Baixar é o que se faz sempre; o resto é ocasional."""

    def test_baixar_fica_em_destaque(self, tela):
        assert '<button class="acao" id="btnZip"' in tela

    def test_o_resto_vai_para_o_mais(self, tela):
        menu = tela.split('id="menuMais"')[1].split("</div>")[0]
        for b in ("btnPdf", "btnAnimar", "btnFinal"):
            assert b in menu

    def test_o_mais_some_quando_nao_ha_nada_dentro(self, tela):
        assert "$('#mais').style.display = [pf, a, f].some(b => !b.hidden) ? '' : 'none';" in tela

    def test_o_menu_fecha_clicando_fora_e_com_esc(self, tela):
        assert "!e.target.closest('#mais')" in tela
        assert "$('#menuMais').hidden = true;" in tela


class TestOAvisoDoArquivoAchatado:
    """"Foto e grafismo só se movem com PSD. PNG, JPEG e PDF chegam
    achatados: aí só dá para mover o que for escrito agora." — mal escrito e
    mal colocado, e a Ligia estava certa nas duas.

    "Achatado" é jargão de Photoshop; "o que for escrito agora" não diz por
    quem nem quando; e o aviso não dizia o que fazer. Solto embaixo da caixa,
    parecia recado geral da tela — ele é o limite de UM modo."""

    def test_fala_do_que_falta_e_do_que_fazer(self, tela):
        # a frase quebra em duas linhas no arquivo: comparar sem os espaços
        corrido = " ".join(tela.split())
        assert "ela é uma imagem só, sem camadas" in corrido
        assert "não há foto, logo nem texto para mover separado" in corrido
        assert "Mande o PSD para poder mexer dentro dela" in corrido
        assert "chegam achatados" not in corrido
        # agora ele explica um modo DESLIGADO, e não um limite de um modo à
        # escolha: a frase precisa dizer isso na primeira palavra
        assert "Indisponível para esta arte" in corrido

    def test_mora_dentro_do_modo_de_que_fala(self, tela):
        modo = tela.split('value="com" checked')[1].split("</label>")[0]
        assert 'id="travaPsd"' in modo

    def test_so_aparece_quando_e_verdade(self, tela):
        """Arquivo achatado. Antes era também "e o modo escolhido": o aviso só
        aparecia depois de marcar o modo que não serve, e era tarde — agora ele
        é o porquê de o modo estar desligado, então aparece junto com a arte."""
        assert "$(porque).hidden = !achatado;" in tela
        assert "'#travaPsd'" in tela


class TestOCampoOrienta:
    """Exemplo dentro do campo se lê como conteúdo já preenchido e some no
    primeiro caractere; orientação se lê como instrução e vale enquanto o
    campo estiver vazio. "Chegamos a Porto Belo" no campo de chamada fazia a
    peça do dia anterior parecer o padrão da casa."""

    def test_nenhum_campo_traz_exemplo_pronto(self, tela):
        for exemplo in ("Chegamos a Porto Belo", "Candidate-se\"",
                        "Save the Date Energiza", "ex.: no Stories"):
            assert exemplo not in tela, exemplo

    def test_os_campos_dizem_o_que_fazer(self, tela):
        for ordem in ("Insira a nova chamada", "Insira o novo call to action",
                      "Dê um nome a esta campanha", "Diga o que esta peça precisa respeitar"):
            assert ordem in tela, ordem


class TestARessalvaTemSaida:
    """"Não gosto dessa ressalva, porque não traz solução: depois de todos os
    pontos, o que a pessoa faz? É isso ou nada?"

    A folha listava o problema e acabava. Agora ela oferece a saída de cada
    caso — e, quando a saída resolve, a ressalva some."""

    def test_a_folha_oferece_ajustar_e_refazer_o_fundo(self, tela):
        assert 'id="resAcoes"' in tela
        assert "Ajustar esta peça</button>" in tela
        assert "Refazer o fundo desta peça" in tela

    def test_refazer_vale_para_aquela_peca_e_nao_para_o_trabalho(self, tela):
        assert "/pecas/${fid}/fundo`, { method: 'POST' }" in tela

    def test_quando_e_o_servico_que_recusou_nao_promete_conserto(self, tela):
        """Credencial ou crédito do generativo não se conserta refazendo: o
        mesmo bloco de cor volta. Oferecer o botão ali seria mentir."""
        assert "const deServico = " in tela or "ehDeServico" in tela
        assert "é credencial ou" in tela
        assert "doFundo && !deServico" in tela

    def test_a_lupa_leva_as_mesmas_saidas(self, tela):
        """É olhando a peça grande que se decide o que fazer com ela."""
        assert 'class="secund refundo"' in tela
        assert 'class="secund verressalva"' in tela

    def test_o_fundo_limpo_apaga_a_ressalva_daquele_formato(self):
        """Era isso que ela cobrou: "isso significa que o erro deveria sumir"."""
        import inspect

        from api import tarefas
        fonte = inspect.getsource(tarefas.refazer_fundo)
        assert "guardados.pop(formato, None)" in fonte
        assert "guardados[formato] = avisos" in fonte


class TestATelaDizQuandoNaoCobra:
    """Instalação de teste com a franquia desligada não pode mostrar um saldo
    que não vale: quem olha "restam 11 peças" acredita nos 11."""

    def test_o_saldo_vira_aviso_de_teste(self, tela):
        assert "franquia desligada" in tela
        assert "if (semLimite){" in tela

    def test_a_tela_pergunta_ao_servidor(self, tela):
        assert "semLimite = /desligada/.test(s.franquia || '');" in tela

    def test_a_ficha_da_conta_tambem_diz(self, tela):
        assert "franquia desligada (teste)" in tela


class TestAPortaNaoInventaEndereco:
    """A porta precisa dizer a quem não tem conta para onde ir. Enquanto o
    domínio não existe, dizer sem link é honesto; escrever um endereço
    plausível manda a pessoa para uma página que não abre."""

    def test_a_porta_nao_tem_dominio_escrito_na_mao(self, tela):
        import re
        pe = tela[tela.find('class="porta-pe"'):]
        pe = pe[:pe.find("</p>")]
        assert not re.search(r"href=\"(https?:|mailto:)", pe), \
            "endereço fixo na porta: ele tem que vir da configuração"

    def test_a_frase_continua_la(self, tela):
        assert "O acesso é criado quando a assinatura é aprovada." in tela

    def test_os_links_vem_do_servidor(self, tela):
        assert "fetch('/porta')" in tela
        assert "p.site_planos" in tela and "p.contato_demo" in tela

    def test_sem_configuracao_nada_aparece(self, tela):
        assert "if (!partes.length) return;" in tela


class TestOsCartoesDePlano:
    """Quatro preços soltos não mostram a escada: o que faz subir de plano
    valer a pena é o preço da peça, e ele tem que estar no cartão."""

    def test_o_cartao_diz_quanto_custa_a_peca(self, tela):
        assert "por peça" in tela
        assert "const porPeca = p =>" in tela

    def test_o_melhor_preco_por_peca_e_apontado(self, tela):
        assert "melhor preço por peça" in tela

    def test_o_preco_vem_do_servidor_e_nao_da_tela(self, tela):
        """Preço escrito na tela envelhece calado: quando a tabela mudar, a
        tela tem que mudar sozinha."""
        import re
        assert "fetch('/planos')" in tela
        assert not re.search(r"R\$\s?\d[\d.,]{2,}", tela), "preço escrito na mão na tela"


class TestQuemTemAcesso:
    """No Agency são até três pessoas na mesma conta. A ficha precisa mostrar
    quem entra, quem ainda não entrou, e deixar tirar o acesso de quem saiu."""

    def test_a_ficha_tem_a_seção_de_acesso(self, tela):
        assert "Quem tem acesso" in tela
        assert 'id="listaPessoas"' in tela

    def test_dá_para_convidar_e_tirar(self, tela):
        assert "fetch('/eu/pessoas', { method:'POST'" in tela
        assert "method:'DELETE'" in tela
        assert "/convite`, { method:'POST' }" in tela

    def test_o_campo_de_convite_some_quando_o_plano_enche(self, tela):
        """Oferecer um campo que vai recusar é convidar para o erro."""
        assert "const cabe = (d.acessos || 1) < (d.limite || 1);" in tela
        assert ".convidar.cheio{display:none}" in tela

    def test_a_ficha_diz_qual_pessoa_sou_eu(self, tela):
        assert "eu.eu && !eu.eu.dono" in tela

    def test_o_convite_que_nao_saiu_nao_e_anunciado_como_enviado(self, tela):
        """E-mail gravado em arquivo não é e-mail entregue: quem vai esperar o
        cliente entrar precisa saber a diferença."""
        assert "function recadoDoConvite(correio)" in tela
        assert "o e-mail não saiu" in tela

    def test_o_editor_avisa_quando_outra_pessoa_salvou(self, tela):
        assert "reabrirPeca" in tela
        assert "versao: ed.versao" in tela
        assert "r.status === 409" in tela

    def test_o_editor_diz_quem_ajustou_antes(self, tela):
        assert "Ajustada por ${pc.mao.nome}" in tela


class TestOFantasmaNaoRoubaOLugarDaPeca:
    """A arte-mãe apagada dentro do cartão vazio é um `<img>`. A tela só
    pintava a peça pronta "se o cartão ainda não tivesse imagem" — e o
    fantasma era uma. O cartão ficava com o PSD inteiro desbotado, sem
    ampliar e sem ajustar, com a peça certa parada no disco."""

    def test_a_guarda_ignora_o_fantasma(self, tela):
        assert "cx.querySelector('img:not(.fantasma), video')" in tela
        assert "if (prontas.has(id) && (!cx.querySelector('img') ||" not in tela

    def test_a_grade_se_redesenha_quando_o_trabalho_comeca(self, tela):
        """Sem isso o fantasma continua lá até alguém clicar num canal."""
        depois = tela.split("job = r.job;")[1][:300]
        assert "pintarFormatos();" in depois

    def test_o_fantasma_sai_quando_a_peca_entra(self, tela):
        """Ele não some por existir trabalho — some por chegar a peça, que é
        escrita por cima dele."""
        assert "cx.innerHTML = `<img src=" in tela


class TestOEditorAbreCheio:
    """"Clico em ajustar e não aparece nada": o `<h2>` do editor tem dois
    filhos — o nome e a medida. Escrever o nome com `textContent` no `<h2>`
    apagava o `<small>` da medida, e a função que desenha a lona morria na
    linha seguinte tentando preenchê-lo. O editor abria vazio: sem peça, sem
    camadas, sem texto."""

    def test_o_nome_tem_caixa_propria(self, tela):
        assert '<span id="edNome">' in tela
        assert "$('#edNome').textContent = `Ajustar" in tela

    def test_ninguem_escreve_por_cima_do_titulo_inteiro(self, tela):
        assert "$('#edTitulo').textContent" not in tela

    def test_a_medida_continua_existindo_para_a_lona(self, tela):
        assert '<small id="edMedida">' in tela
        assert "$('#edMedida').textContent" in tela


class TestOFantasmaMostraAPranchetaEscolhida:
    """Num PSD de várias pranchetas, a miniatura do arquivo é o PSD INTEIRO.
    Depois de escolher uma prancheta, o cartão vazio tem que mostrar ELA — e
    não o desenho das seis, que foi o que ela viu."""

    def test_o_fantasma_tem_fonte_propria(self, tela):
        assert "function fonteDoFantasma()" in tela
        assert "if (pranchetaEscolhida) return pranchetaEscolhida;" in tela

    def test_escolher_a_prancheta_troca_a_fonte(self, tela):
        depois = tela.split("async function mandarPrancheta(")[1].split("\n}")[0]
        assert "pranchetaEscolhida = `/jobs/${job}/arquivos/" in depois
        assert "pintarFormatos();" in depois

    def test_arte_nova_esquece_a_prancheta_anterior(self, tela):
        depois = tela.split("async function receber(f)")[1][:1200]
        assert "pranchetaEscolhida = null" in depois

    def test_o_fantasma_nao_depende_mais_de_nao_haver_trabalho(self, tela):
        """Era isso que deixava o cartão vazio com um xadrez cinza enquanto a
        peça não ficava pronta: o trabalho já existia, e o fantasma sumia."""
        assert "const fantasma = previa && !job" not in tela


class TestAOrdemDoEnvio:
    """A arte sobe quando é solta, não no clique final. Num PSD de 190 MB a
    espera passa a acontecer enquanto a pessoa decide, e a pergunta da
    prancheta chega ANTES dos formatos — que é a ordem certa, porque a
    prancheta decide o que cada formato vai recortar."""

    def test_soltar_a_arte_ja_sobe(self, tela):
        assert "async function subirArte()" in tela
        depois = tela.split("async function receber(f)")[1].split("async function subirArte")[0]
        assert "await subirArte();" in depois

    def test_o_botao_manda_rodar_o_rascunho(self, tela):
        """Sem isso a arte subiria duas vezes."""
        assert "fetch(`/jobs/${rascunho}/rodar`" in tela
        assert "fd.append('arte', peca.arquivo)" in tela.split("$('#btnIr').onclick")[0]
        assert "fd.append('arte'" not in tela.split("$('#btnIr').onclick")[1][:900]

    def test_a_prancheta_e_perguntada_no_envio(self, tela):
        depois = tela.split("async function subirArte()")[1][:1400]
        assert "escolherPrancheta(r.pranchetas)" in depois

    def test_escolher_a_prancheta_num_rascunho_nao_acompanha(self, tela):
        """Não há fila para acompanhar: o trabalho ainda nem tem formatos."""
        depois = tela.split("async function mandarPrancheta(")[1].split("\n}")[0]
        assert "if (rascunho){" in depois

    def test_a_grade_continua_clicavel_durante_o_rascunho(self, tela):
        """O defeito que isso evita: com a arte já no servidor, a tela achava
        que o trabalho estava rodando e travava a escolha dos formatos."""
        assert "const escolhendo = () => !job || !!rascunho;" in tela
        assert "if (!escolhendo()) return;" in tela
        assert "if (job) return;" not in tela

    def test_o_botao_espera_a_prancheta(self, tela):
        assert "const esperaPrancheta =" in tela
        assert "!esperaPrancheta" in tela


class TestAVezDeCadaEscolha:
    """Ela descreveu a sequência: "sobe o PSD, ele diz que já pode escolher o
    formato, eu escolho, aí abre a janela da prancheta, escolho e ele continua
    pedindo prancheta e não libera". Duas coisas: a escolha da prancheta
    dependia da IMAGEM dela, que é composta depois; e os formatos ficavam
    abertos antes da vez deles."""

    def test_a_escolha_vale_antes_da_imagem(self, tela):
        assert "let pranchetaNome = null" in tela
        assert "const esperaPrancheta = !!(ultimasPranchetas || []).length && !pranchetaNome;" in tela
        depois = tela.split("async function mandarPrancheta(")[1].split("\n}")[0]
        assert "pranchetaNome = nome;" in depois

    def test_a_imagem_chega_depois_e_a_tela_troca_sozinha(self, tela):
        assert "function esperarAPrevia(nome)" in tela
        assert "olhoNaPreviaEscolhida" in tela

    def test_enquanto_le_o_arquivo_a_tela_diz(self, tela):
        assert "let lendoArte = false" in tela
        assert "Lendo o arquivo…" in tela

    def test_os_canais_ficam_de_molho_ate_a_vez_deles(self, tela):
        assert "classList.toggle('demolho', aindaNao)" in tela
        assert "#canais.demolho{opacity:.35;pointer-events:none}" in tela

    def test_a_grade_diz_qual_e_a_etapa(self, tela):
        assert "<b>Escolha a prancheta</b> para ver os formatos" in tela
        assert "Agora escolha um canal acima" in tela


class TestABarraDoVideo:
    """"Quando solicito animação da peça não dá pra saber se está ou não
    acontecendo, fica parado sem barra de progresso."

    A barra existia e já era alimentada pelo vídeo — mas pela única conta que
    o estado trazia: prontos sobre formatos. Como o estado só era gravado no
    fim, isso era zero do começo ao fim do render.
    """

    def test_a_barra_do_video_le_o_passo_e_nao_so_o_que_acabou(self, tela):
        assert "PESO_VIDEO" in tela, "o vídeo não tem peso por etapa"
        assert "v.feito ?? (v.prontos||[]).length" in tela

    def test_o_detalhe_diz_a_etapa_e_o_formato(self, tela):
        """"2 de 5 vídeos" não distingue um render andando de um travado."""
        assert "v.etapa || 'montando o vídeo'" in tela

    def test_a_estimativa_usa_o_relogio_do_video(self, tela):
        """Era o da replicação, que pode ter sido ontem."""
        assert "? v.desde : ((d.progresso || {}).desde || d.inicio)" in tela

    def test_a_trilha_mostra_que_esta_viva(self, tela):
        """Fração verdadeira e parada minutos a fio volta a parecer travamento."""
        assert ".trilha.trabalhando::after" in tela
        assert "trilha.classList.toggle('trabalhando', andandoAlgo)" in tela
        assert "$('#andTrilha').classList.toggle('trabalhando', tem)" in tela

    def test_quem_desliga_animacao_ve_a_barra_parada(self, tela):
        """Acessibilidade: o brilho que atravessa é decoração, não informação."""
        i = tela.find(".trilha.trabalhando::after")
        assert i > 0
        regra = tela[i:i + 600]
        assert "prefers-reduced-motion" in regra
        assert "animation:none" in regra.split("prefers-reduced-motion")[1]

    def test_o_painel_abre_no_clique_e_nao_na_proxima_volta(self, tela):
        """Eram dois segundos e meio de tela parada logo depois do clique —
        justamente quando a dúvida é se o pedido chegou."""
        i = tela.find("$('#btnAnimarOk').onclick")
        assert i > 0
        assert "espelhar(true, null)" in tela[i:i + 900]


class TestOModoQueAArteComporta:
    """"Se ele não possibilita ajuste de diagramação de logo, de fonte, porque
    é uma peça estática, não deveria ter as outras opções."

    "Adaptação + Ajustes" era o modo marcado por padrão. Com JPEG ou PNG ele
    entregava exatamente a mesma peça do primeiro modo e abria um editor sem
    nada para mover — a tela avisava disso em letra miúda, depois de escolhido.
    Avisar não resolve: o modo sai da mesa.
    """

    def test_os_dois_modos_que_mexem_na_arte_desligam(self, tela):
        """Ajustar não tem o que mover; escrever não tem como corrigir."""
        assert "PRECISA_DE_CAMADAS = { com: '#travaPsd', novo: '#travaTexto' }" in tela
        assert "r.disabled = achatado;" in tela

    def test_e_a_escolha_cai_para_o_que_a_arte_permite(self, tela):
        assert "if (trocar) document.querySelector(`input[name=modo][value=sem]`" in tela \
            or "if (trocar) document.querySelector('input[name=modo][value=sem]')" in tela

    def test_o_porque_fica_a_vista_e_nao_so_quando_escolhido(self, tela):
        """Antes o aviso só aparecia depois de marcar o modo que não serve."""
        assert "$(porque).hidden = !achatado;" in tela
        assert "label.modo.fora small.travado" in tela

    def test_cada_modo_desligado_diz_o_seu_proprio_porque(self, tela):
        """Os dois motivos são diferentes, e dizer o errado é não dizer nada:
        um não tem o que mover, o outro não tem como corrigir."""
        corrido = " ".join(tela.split())
        assert "não há foto, logo nem texto para mover separado" in corrido
        assert "sem camadas não há como ajustar o que for escrito" in corrido

    def test_o_modo_desligado_continua_na_tela(self, tela):
        """Sumir faria parecer que a plataforma não faz — ela faz, com PSD."""
        assert "label.modo.fora{opacity:" in tela


class TestORodapeEnquantoOArquivoAbre:
    """"O texto do rodapé não deveria apresentar essa info de ir escolhendo a
    arte enquanto está lendo o PSD."

    O rodapé dizia "já pode ir escolhendo" ao mesmo tempo que o meio da tela
    dizia "se ele tiver mais de uma arte dentro, eu já pergunto qual é" — duas
    ordens opostas na mesma tela. E a errada era a do rodapé: a prancheta
    decide o que cada formato recorta, então escolher antes dela é escolher na
    ordem errada.
    """

    def test_o_rodape_nao_manda_escolher_enquanto_le(self, tela):
        assert "já pode ir escolhendo" not in tela

    def test_ele_diz_a_ordem(self, tela):
        """Não basta tirar o convite: sem dizer o que vem depois, a espera
        parece travamento."""
        assert "A escolha vem depois que ele abrir." in tela

    def test_e_o_meio_da_tela_continua_dizendo_o_que_vai_acontecer(self, tela):
        corrido = " ".join(tela.split())
        assert "num PSD grande isto leva um tempo" in corrido
        assert "eu já pergunto qual é" in corrido
