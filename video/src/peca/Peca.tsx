/**
 * Anima UMA peça já adaptada pela ReplicAI.
 *
 * A entrada é o próprio `replicas/pecas/<formato>.json`: fundo, elementos com
 * caixa, fontes. Nada aqui decide layout — isso já foi decidido por formato.
 * Texto entra como TEXTO, não como PNG: refluí, fica nítido e pode animar por
 * palavra. Toda fonte é arquivo local; link do Google trava o render.
 */
import React from 'react';
import {
  AbsoluteFill, Img, Video, staticFile, useCurrentFrame, useVideoConfig,
  interpolate, spring, delayRender, continueRender,
} from 'remotion';
import { PRESETS, papelDe, grupoDe, type Papel, type Revela } from './movimento';

type Caixa = { x: number; y: number; w: number; h: number };
type El = {
  // `botao` é o CTA com corpo próprio: pílula de cor com a letra dentro.
  // Sem ele no tipo, o elemento caía no ramo de texto e o CTA sumia no fundo.
  tipo: 'imagem' | 'texto' | 'video' | 'botao';
  papel?: string; src?: string; box: Caixa; fit?: string;
  texto?: string; fonte?: string; peso?: number; cor?: string;
  tamanho?: number; lineHeight?: number; align?: string; valign?: string;
  rotacao?: number; opacidade?: number;
  min?: number; max?: number; quebra?: boolean;
  sombra?: string; fallback?: string; italico?: boolean; sublinhado?: boolean;
  acento?: string; letterSpacing?: string;
  fundo?: string; raio?: number;        // só do botão: cor do corpo e o arredondamento
};
export type PecaProps = {
  base: string;                        // pasta em public/, ex. "peca/kv-stories"
  canvas: { w: number; h: number };
  fundo?: { tipo?: string; src?: string; cor?: string; fit?: string };
  elementos: El[];
  fontes?: { familia: string; arquivo: string; peso?: number }[];
  preset?: keyof typeof PRESETS;
  segundos?: number;
};

const arquivoDe = (base: string, src: string) =>
  staticFile(`${base}/${src.split('/').pop()}`);

/** A regra @font-face precisa existir no DOM já no commit do render, e não
 *  num efeito: efeito de filho roda antes de efeito de pai, então o texto
 *  media o próprio tamanho quando a fonte ainda nem tinha sido declarada. */
const cssDasFontes = (base: string, fontes: PecaProps['fontes']) =>
  (fontes || []).map((f) =>
    `@font-face{font-family:"${f.familia}";font-weight:${f.peso || 400};` +
    `src:url("${arquivoDe(base, f.arquivo)}") format("truetype");font-display:block}`
  ).join('\n');

/** Segura o quadro até as fontes declaradas estarem de fato carregadas. */
const useFontesProntas = () => {
  const [espera] = React.useState(() => delayRender('fontes'));
  React.useEffect(() => {
    document.fonts.ready.then(() => continueRender(espera));
  }, [espera]);
};

/**
 * O motor estático não grava o corpo do texto: grava `min`/`max` e acha o
 * tamanho por busca binária, para a frase encher a caixa. Sem repetir isso
 * aqui, o texto sai no corpo padrão do navegador — minúsculo.
 */
type Pedaco = { txt: string; acento?: boolean; forte?: boolean };

/** `{{assim}}` pinta com a cor de acento e `**assim**` engrossa — a mesma
 *  marcação do motor estático. Devolve pedaços, não JSX, porque a animação
 *  precisa quebrar isso em linhas, palavras ou letras sem perder o estilo. */
const pedacos = (txt: string): Pedaco[][] =>
  txt.split('\n').map((linha) =>
    linha.split(/(\{\{.+?\}\}|\*\*.+?\*\*)/g).filter(Boolean).map((p) =>
      p.startsWith('{{') && p.endsWith('}}') ? { txt: p.slice(2, -2), acento: true }
      : p.startsWith('**') && p.endsWith('**') ? { txt: p.slice(2, -2), forte: true }
      : { txt: p }));

const estiloDe = (p: Pedaco, acento?: string): React.CSSProperties => ({
  color: p.acento ? (acento || 'inherit') : undefined,
  fontWeight: p.forte ? 800 : undefined,
});

/** quebra uma linha em unidades animáveis, mantendo o estilo de cada pedaço */
const unidades = (linha: Pedaco[], modo: 'palavra' | 'letra') =>
  linha.flatMap((p) =>
    (modo === 'palavra' ? p.txt.split(/(\s+)/) : [...p.txt])
      .filter((u) => u !== '')
      .map((u) => ({ u, p })));

/** Sem o trava em [0,1] a curva não termina: passado o tempo da animação,
 *  (1-x) vira negativo, o cubo mantém o sinal e o valor dispara. O texto
 *  continuava subindo para sempre — a tremedeira e o sumiço no fim vinham daqui. */
/** Variação fixa por posição da letra. Precisa ser calculada, e não sorteada:
 *  o Remotion rende em várias abas e um Math.random daria valores diferentes
 *  em cada uma, fazendo a letra pular de lugar no meio do vídeo. */
const aleatorio = (k: number) => {
  const x = Math.sin((k + 1) * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

const suaveOut = (x: number) => {
  const c = Math.min(1, Math.max(0, x));
  return 1 - Math.pow(1 - c, 3);
};

/** Já assentou? Então nada de transform nem filtro: com translate quebrado a
 *  letra é reamostrada a cada quadro e fica vibrando no lugar. */
const parado = (p: number) => p >= 1;

/** Começa devagar e termina devagar. A assinatura precisa disso: com uma curva
 *  que dispara no primeiro quadro, ela cruza a peça enquanto o resto ainda está
 *  saindo e o meio do caminho fica embolado. Assim ela espera, desliza e pousa. */
const suaveInOut = (x: number) => {
  const c = Math.min(1, Math.max(0, x));
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
};

const TextoAjustado: React.FC<{
  e: El; style: React.CSSProperties; t0: number; revela: Revela; passo: number; fps: number; t: number;
}> = ({ e, style, t0, revela, passo, fps, t }) => {
  const caixa = React.useRef<HTMLDivElement>(null);
  const alvo = React.useRef<HTMLSpanElement>(null);
  const [corpo, setCorpo] = React.useState<number | null>(e.tamanho ?? null);
  const [espera] = React.useState(() => (e.tamanho ? null : delayRender('ajuste-texto')));
  const jaLiberou = React.useRef(false);

  // O Remotion entrega um objeto novo de elemento a cada quadro. Se o efeito
  // depender do objeto, ele remede 150 vezes e o corpo pode cair meio ponto
  // diferente em cada uma: o texto nunca para quieto. A dependência tem que ser
  // o conteúdo, não a identidade.
  const assinatura = [e.texto, e.fonte, e.peso, e.box.w, e.box.h, e.min, e.max,
                      e.lineHeight, e.letterSpacing, e.quebra].join('|');

  React.useEffect(() => {
    if (e.tamanho) return;
    let vivo = true;
    (async () => {
      // Medir antes da fonte chegar dá um corpo calculado com a fonte de reserva.
      // Como cada quadro renderiza sozinho, o valor saía diferente de um quadro
      // para o outro e o texto tremia no lugar. Espera a fonte certa.
      try {
        await document.fonts.load(`${e.peso || 400} 100px "${e.fonte || 'sans-serif'}"`);
        await document.fonts.ready;
      } catch { /* sem a fonte, mede com a reserva mesmo */ }
      if (!vivo || !caixa.current || !alvo.current) {
        if (espera !== null && !jaLiberou.current) { jaLiberou.current = true; continueRender(espera); }
        return;
      }
      const c = caixa.current, a = alvo.current;
      const cabe = () => a.scrollHeight <= c.clientHeight + 0.5 && a.scrollWidth <= c.clientWidth + 0.5;
      // Em pixels INTEIROS. O Remotion rende os quadros em várias abas ao mesmo
      // tempo e cada uma mede por conta própria; com meio pixel de diferença o
      // texto saía em duas posições alternadas, quadro sim quadro não. Inteiro
      // faz as duas medições caírem no mesmo valor.
      let lo = Math.ceil(e.min ?? 18), hi = Math.floor(e.max ?? e.box.h), melhor = lo;
      if (lo > hi) [lo, hi] = [hi, lo];
      while (lo <= hi) {
        const meio = Math.floor((lo + hi) / 2);
        a.style.fontSize = `${meio}px`;
        if (cabe()) { melhor = meio; lo = meio + 1; } else { hi = meio - 1; }
      }
      a.style.fontSize = `${melhor}px`;   // DOM e React falando o mesmo valor
      setCorpo(melhor);
      if (espera !== null && !jaLiberou.current) { jaLiberou.current = true; continueRender(espera); }
    })();
    return () => { vivo = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assinatura, espera]);

  const linhas = pedacos(e.texto || '');
  const jh = e.align === 'center' ? 'center' : e.align === 'right' ? 'flex-end' : 'flex-start';
  const jv = e.valign === 'middle' ? 'center' : e.valign === 'bottom' ? 'flex-end' : 'flex-start';
  const alinhaLinha = e.align === 'center' ? 'center' : e.align === 'right' ? 'right' : 'left';

  let n = 0;   // contador global de unidades, para a cascata atravessar as linhas

  const conteudo = linhas.map((linha, li) => {
    if (revela === 'mascara') {
      // a linha sobe por trás de um corte duro. Sem fade: é o corte que revela.
      const p = suaveOut((t - (t0 + li * passo)) / 0.52);
      return (
        <span key={li} style={{ display: 'block', overflow: 'hidden', textAlign: alinhaLinha,
                                paddingBottom: '0.14em', marginBottom: '-0.14em' }}>
          <span style={{ display: 'inline-block',
            transform: parado(p) ? undefined : `translateY(${(1 - p) * 110}%)` }}>
            {linha.map((pc, i) => <span key={i} style={estiloDe(pc, e.acento)}>{pc.txt}</span>)}
          </span>
        </span>
      );
    }
    // Letra a letra só faz sentido em tipo de display. Numa frase longa a
    // cascata levaria segundos e, pior, cada letra perde a leitura individual.
    // O corte é pelo próprio conteúdo: texto curto é lettering, frase é palavra.
    const curto = (e.texto || '').replace(/\s/g, '').length <= 18;
    const modo: 'palavra' | 'letra' =
      revela === 'palavra' ? 'palavra'
      : revela === 'lettering' && !curto ? 'palavra'
      : 'letra';
    const comoEntra: Revela = revela === 'lettering' && !curto ? 'palavra' : revela;
    const us = unidades(linha, modo);
    return (
      <span key={li} style={{ display: 'block', textAlign: alinhaLinha }}>
        {us.map((x, i) => {
          if (/^\s+$/.test(x.u)) return <span key={i}>{x.u}</span>;
          const meu = t0 + (n++) * passo;
          if (comoEntra === 'palavra') {
            // A mola precisa de um fim declarado. Sem `durationInFrames` ela se
            // aproxima de 1 sem nunca chegar: o deslocamento fica preso em fração
            // de pixel e a letra é redesenhada fora de lugar a cada quadro. Era
            // daí que vinha a tremedeira no fim do vídeo.
            const DUR = 0.55;
            const mola = spring({ frame: (t - meu) * fps, fps,
              durationInFrames: Math.round(DUR * fps),
              config: { damping: 19, stiffness: 200, mass: 0.6 } });
            const fim = t - meu >= DUR;
            if (t < meu) return <span key={i} style={{ display: 'inline-block', opacity: 0 }}>{x.u}</span>;
            return (
              <span key={i} style={{ display: 'inline-block', ...estiloDe(x.p, e.acento),
                opacity: fim ? 1 : Math.min(1, mola * 2),
                transform: fim ? undefined
                  : `translateY(${(1 - mola) * 28}%) scale(${0.72 + 0.28 * mola})`,
                transformOrigin: 'bottom left' }}>{x.u}</span>
            );
          }
          if (comoEntra === 'lettering') {
            // Cada letra com movimento próprio: sobe, gira e cresce passando do
            // ponto antes de assentar. O giro alterna de lado para dar cadência
            // em vez de um desfile de letras iguais.
            // Curta, para a letra assentar antes da próxima sair. Com 0,62s de
            // queda e 34ms de intervalo havia sete letras no ar juntas e o olho
            // lia uma onda só, não letras soltas.
            const DUR = 0.40;
            const m = spring({ frame: (t - meu) * fps, fps,
              durationInFrames: Math.round(DUR * fps),
              config: { damping: 11, stiffness: 170, mass: 0.7 } });
            const quieta = t - meu >= DUR;
            if (t < meu) return <span key={i} style={{ display: 'inline-block', opacity: 0 }}>{x.u}</span>;
            const r = aleatorio(i);          // fixo por posição: igual em toda aba
            const lado = i % 2 === 0 ? 1 : -1;
            const giro = (18 + r * 20) * lado;
            const sobe = 95 + r * 70;
            const anda = (r - 0.5) * 26;
            return (
              <span key={i} style={{ display: 'inline-block', ...estiloDe(x.p, e.acento),
                opacity: quieta ? 1 : Math.min(1, m * 3.5),
                transform: quieta ? undefined
                  : `translate(${(1 - m) * anda}%, ${(1 - m) * sobe}%) ` +
                    `rotate(${(1 - m) * giro}deg) scale(${0.12 + 0.88 * m})`,
                transformOrigin: '50% 100%' }}>{x.u}</span>
            );
          }
          // letra: sai de desfoque e de entrelinha aberta, bem devagar
          const p = suaveOut((t - meu) / 0.7);
          if (p <= 0) return <span key={i} style={{ display: 'inline-block', opacity: 0 }}>{x.u}</span>;
          return (
            <span key={i} style={{ display: 'inline-block', ...estiloDe(x.p, e.acento),
              opacity: p,
              filter: parado(p) ? undefined : `blur(${(1 - p) * 10}px)`,
              transform: parado(p) ? undefined : `translateY(${(1 - p) * 14}%)` }}>{x.u}</span>
          );
        })}
      </span>
    );
  });

  return (
    <div ref={caixa} style={{ ...style, display: 'flex', justifyContent: jh, alignItems: jv, overflow: 'hidden' }}>
      <span ref={alvo} style={{
        fontFamily: `"${e.fonte || 'sans-serif'}"${e.fallback ? ', ' + e.fallback : ''}`,
        fontWeight: e.peso || 400, color: e.cor || '#fff',
        fontSize: corpo ?? (e.min ?? 18), lineHeight: e.lineHeight || 1.1,
        textAlign: (e.align || 'left') as any,
        whiteSpace: e.quebra === false ? 'pre' : 'pre-wrap',
        width: '100%', textShadow: e.sombra || undefined, letterSpacing: e.letterSpacing,
        textDecoration: [e.sublinhado && 'underline'].filter(Boolean).join(' ') || undefined,
        fontStyle: e.italico ? 'italic' : undefined,
      }}>{conteudo}</span>
    </div>
  );
};

export const Peca: React.FC<PecaProps> = ({
  base, canvas, fundo, elementos, fontes, preset = 'energia', segundos = 5,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const P = PRESETS[preset] ?? PRESETS.energia;
  useFontesProntas();
  const cssFontes = cssDasFontes(base, fontes);

  // cascata: cada papel conta os próprios irmãos, na ordem em que aparecem
  const contagem: Partial<Record<Papel, number>> = {};
  const jaVisto: Record<string, number> = {};
  const comTempo = elementos.map((e) => {
    const nome = e.papel || e.tipo;
    const pap = papelDe(nome, e.tipo);
    const m = P.por[pap];
    const g = `${pap}:${grupoDe(nome)}`;
    if (jaVisto[g] === undefined) {
      const i = contagem[pap] ?? 0;
      contagem[pap] = i + 1;
      jaVisto[g] = m.atraso + i * m.cascata;
    }
    return { e, pap, t0: jaVisto[g], m };
  });

  // zoom lento e contínuo no fundo: dá vida sem competir com os elementos
  // Tudo termina antes do fim do vídeo: os últimos 0,30s são cartela parada.
  // Sem isso a saída dos elementos e o zoom do fundo seguem até o último quadro
  // e a assinatura nunca chega a pousar de verdade.
  const PAUSA = 0.30;
  const fimDoFecho = Math.max(0.5, segundos - PAUSA);

  const zoom = interpolate(t, [0, fimDoFecho], [P.zoomBase, 1], { extrapolateRight: 'clamp' });

  // A saída é em cascata, na ordem em que entrou: o CTA é dos últimos, então a
  // chamada fica na tela o máximo possível.
  const S = P.saida;
  const ordemSaida = [...comTempo].sort((a, b) => a.t0 - b.t0).map(x => x.e);
  // A cascata encolhe conforme o número de elementos: numa peça com treze
  // camadas, o intervalo cheio faria a saída começar antes de a peça ter sido
  // vista montada. A janela inteira nunca passa de JANELA segundos.
  const JANELA = 1.05;
  const nEl = Math.max(1, ordemSaida.length - 1);
  const cascEf = Math.min(S.cascata, Math.max(0, JANELA - S.dur) / nEl);
  const inicioSaida = fimDoFecho - S.dur - cascEf * nEl;
  const saidaDe = (el: El) => {
    const i = ordemSaida.indexOf(el);
    return Math.min(1, Math.max(0, (t - (inicioSaida + i * cascEf)) / S.dur));
  };

  // A assinatura não sai: caminha para o centro e fica. É a MAIOR marca da peça
  // — a logo bordada na manga do personagem também conta como marca, e ela é
  // arte, não assinatura: tem que sair com o resto em vez de voar para o meio.
  const marcas = comTempo.filter((x) => x.pap === 'marca');
  const assinatura = marcas.length
    ? marcas.reduce((a, b) => (a.e.box.w * a.e.box.h >= b.e.box.w * b.e.box.h ? a : b)).e
    : null;
  const pFecho = suaveInOut((t - inicioSaida) / Math.max(0.25, fimDoFecho - inicioSaida));

  return (
    <AbsoluteFill style={{ backgroundColor: fundo?.cor || '#000', overflow: 'hidden' }}>
      <style dangerouslySetInnerHTML={{ __html: cssFontes }} />
      {fundo?.src && (
        <AbsoluteFill style={{ transform: `scale(${zoom})` }}>
          <Img src={arquivoDe(base, fundo.src)}
               style={{ width: '100%', height: '100%', objectFit: (fundo.fit === 'stretch' ? 'fill' : 'cover') as any }} />
        </AbsoluteFill>
      )}

      {comTempo.map(({ e, pap, t0, m }, k) => {
        const bruto = (t - t0) / m.dur;
        if (bruto <= 0) return null;
        const p = m.mola
          ? spring({ frame: frame - t0 * fps, fps, config: { damping: 14, stiffness: 120, mass: 0.8 } })
          : interpolate(bruto, [0, 1], [0, 1], { extrapolateRight: 'clamp', easing: (x) => 1 - Math.pow(1 - x, 3) });

        const sai = saidaDe(e);
        const fundoDaPeca = pap === 'base';

        // Depois de pousar, imagem não congela: anda devagar num rumo próprio.
        // É o que separa uma peça viva de um PNG com fade. Texto fica parado,
        // porque texto que se mexe embaixo do olho cansa a leitura.
        const deriva = (e.tipo === 'imagem' || e.tipo === 'video') && !fundoDaPeca
          ? (t / segundos) * (2.5 + aleatorio(k) * 3.5) * (k % 2 ? -1 : 1)
          : 0;

        const dy = m.dy * (1 - p) + deriva + S.dy * sai;
        const esc = (m.escala + (1 - m.escala) * p) * (1 + (S.escala - 1) * sai);
        const giro = (e.rotacao || 0) + S.gira * sai * (k % 2 ? 1 : -1);
        const estilo: React.CSSProperties = {
          position: 'absolute',
          left: e.box.x, top: e.box.y, width: e.box.w, height: e.box.h,
          opacity: Math.min(1, p) * (e.opacidade ?? 1) * (1 - sai),
          transform: `translateY(${dy}px) scale(${fundoDaPeca ? esc * zoom : esc})`
            + (giro ? ` rotate(${giro}deg)` : ''),
          transformOrigin: 'center',
        };

        // a assinatura ignora a saída: em vez de sumir, vai ao centro e cresce
        if (e === assinatura && pFecho > 0) {
          const paraX = canvas.w / 2 - (e.box.x + e.box.w / 2);
          const paraY = canvas.h / 2 - (e.box.y + e.box.h / 2);
          // cresce até ocupar ~38% da largura, que é tamanho de cartela de fecho,
          // mas nunca encolhe: num banner pequeno a logo já chega grande
          const alvo = Math.min(3.2, Math.max(1, (canvas.w * 0.38) / e.box.w));
          estilo.opacity = Math.min(1, p) * (e.opacidade ?? 1);
          estilo.transform =
            `translate(${paraX * pFecho}px, ${paraY * pFecho}px) scale(${1 + (alvo - 1) * pFecho})`;
        }

        if (e.tipo === 'video' && e.src)
          return <Video key={k} src={arquivoDe(base, e.src)} style={{ ...estilo, objectFit: 'cover' }} />;
        if (e.tipo === 'imagem' && e.src)
          return <Img key={k} src={arquivoDe(base, e.src)}
                      style={{ ...estilo, objectFit: (e.fit === 'fill' ? 'fill' : e.fit === 'cover' ? 'cover' : 'contain') as any }} />;

        // O botão chega inteiro, como bloco. Sem este ramo ele caía no ramo de
        // texto: a letra escura era desenhada sem a pílula atrás e o CTA sumia
        // no fundo escuro — o vídeo entregava a peça sem a chamada para ação.
        if (e.tipo === 'botao') {
          const corpo = e.tamanho || Math.round(e.box.h * 0.42);
          return (
            <div key={k} style={{
              ...estilo,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: e.fundo || '#ffffff',
              color: e.cor || '#101828',
              borderRadius: e.raio ?? Math.round(e.box.h / 2),
              fontFamily: e.fonte || 'inherit',
              fontWeight: e.peso || 700,
              fontSize: corpo,
              letterSpacing: e.letterSpacing || 'normal',
              whiteSpace: 'nowrap',
            }}>{e.texto}</div>
          );
        }

        // o texto se anima por dentro: o invólucro não translada nem some
        const semEntrada: React.CSSProperties = {
          ...estilo,
          opacity: (e.opacidade ?? 1) * (1 - sai),
          transform: sai > 0 ? `translateY(${S.dy * sai}px) scale(${1 + (S.escala - 1) * sai})` : undefined,
        };
        return <TextoAjustado key={k} e={e} style={semEntrada} t0={t0}
                 revela={P.revela} passo={P.passo} fps={fps} t={t} />;
      })}
    </AbsoluteFill>
  );
};
