/**
 * A linguagem de movimento. A peça diz ONDE cada coisa está; isto diz QUANDO
 * e COMO ela chega. Separado de propósito: trocar de preset não mexe no layout.
 */
export type Papel = 'base' | 'scrim' | 'marca' | 'objeto' | 'texto';

export const papelDe = (nome: string, tipo?: string): Papel => {
  const n = (nome || '').toLowerCase();
  if (/^(foto|imagem|fundo|bg|key)/.test(n)) return 'base';
  // "sombra-topo" é um scrim do fundo; "postit-sombra" é a sombra de um objeto.
  // O que decide é a sombra estar sozinha ou ser sufixo de outra coisa.
  if (/^(sombra|scrim|degrade|gradiente|overlay)/.test(n)) return 'scrim';
  if (/logo|marca|selo|assinatura/.test(n)) return 'marca';
  if (tipo === 'texto') return 'texto';
  if (/texto|headline|titulo|data|local|endereco|cta|copy|apoio/.test(n)) return 'texto';
  return 'objeto';
};

/** Partes do mesmo objeto chegam juntas: "postit-sombra", "postit-papel" e
 *  "postit-fita" são um post-it só, não três coisas em cascata. */
export const grupoDe = (nome: string) => (nome || '').toLowerCase().split(/[-_ ]/)[0] || '';

export type Entrada = {
  atraso: number;      // segundos até começar
  dur: number;         // segundos de entrada
  dy: number;          // de quanto sobe/desce, em px do canvas
  escala: number;      // escala inicial (1 = nenhuma)
  mola: boolean;
  cascata: number;     // intervalo entre irmãos do mesmo papel
};

/** Como o texto se revela. É isto que separa um preset do outro — não a velocidade.
 *  mascara: cada linha sobe por trás de um corte duro, sem fade. Padrão de agência.
 *  palavra: palavra por palavra, com estalo de escala e overshoot.
 *  letra:   letra por letra, saindo de desfoque e de entrelinha aberta.
 *  lettering: letra por letra, cada uma com movimento próprio — gira, cresce
 *             e assenta passando do ponto. É animação de letra, não revelação. */
export type Revela = 'mascara' | 'palavra' | 'letra' | 'lettering';

/** Saída da peça. Sem ela o vídeo entra, congela e corta seco — e no Reels,
 *  que repete sozinho, o salto do último quadro para o primeiro fica evidente.
 *  Com saída o fim volta ao vazio e a repetição parece intencional.
 *  `dur` é quanto dura, `cascata` o intervalo entre blocos saindo. */
export type Saida = { dur: number; cascata: number; dy: number; escala: number; gira: number };

export type Preset = {
  nome: string; zoomBase: number; revela: Revela; passo: number;
  saida: Saida; por: Record<Papel, Entrada>;
};

export const PRESETS: Record<string, Preset> = {
  // Direto. Para banner e formato pequeno, onde não há tempo a perder.
  seco: {
    nome: 'Corte',
    revela: 'mascara',
    passo: 0.09,          // intervalo entre LINHAS dentro do mesmo bloco
    zoomBase: 1.03,
    saida: { dur: 0.42, cascata: 0.05, dy: -26, escala: 1.00, gira: 0 },
    por: {
      base:   { atraso: 0.00, dur: 0.45, dy: 0,   escala: 1.04, mola: false, cascata: 0 },
      scrim:  { atraso: 0.20, dur: 0.35, dy: 0,   escala: 1,    mola: false, cascata: 0 },
      marca:  { atraso: 0.35, dur: 0.35, dy: -12, escala: 1,    mola: false, cascata: 0 },
      objeto: { atraso: 0.50, dur: 0.40, dy: 26,  escala: 1,    mola: false, cascata: 0.06 },
      texto:  { atraso: 0.70, dur: 0.35, dy: 18,  escala: 1,    mola: false, cascata: 0.08 },
    },
  },
  // Com peso. O objeto chega com overshoot, o texto em cascata marcada.
  energia: {
    nome: 'Impacto',
    revela: 'palavra',
    passo: 0.07,          // intervalo entre PALAVRAS
    zoomBase: 1.06,
    saida: { dur: 0.46, cascata: 0.06, dy:  34, escala: 0.92, gira: 0 },
    por: {
      base:   { atraso: 0.00, dur: 0.60, dy: 0,   escala: 1.07, mola: false, cascata: 0 },
      scrim:  { atraso: 0.30, dur: 0.45, dy: 0,   escala: 1,    mola: false, cascata: 0 },
      marca:  { atraso: 0.55, dur: 0.50, dy: -20, escala: 0.94, mola: true,  cascata: 0 },
      objeto: { atraso: 0.85, dur: 0.70, dy: 54,  escala: 0.96, mola: true,  cascata: 0.09 },
      texto:  { atraso: 1.20, dur: 0.45, dy: 30,  escala: 1,    mola: false, cascata: 0.12 },
    },
  },
  // Calmo e longo. Para peça de imagem, onde a foto é a protagonista.
  editorial: {
    nome: 'Editorial',
    revela: 'letra',
    passo: 0.022,         // intervalo entre LETRAS
    zoomBase: 1.10,
    saida: { dur: 0.70, cascata: 0.09, dy: -30, escala: 1.02, gira: 0 },
    por: {
      base:   { atraso: 0.00, dur: 1.10, dy: 0,   escala: 1.10, mola: false, cascata: 0 },
      scrim:  { atraso: 0.50, dur: 0.80, dy: 0,   escala: 1,    mola: false, cascata: 0 },
      marca:  { atraso: 0.90, dur: 0.70, dy: -10, escala: 1,    mola: false, cascata: 0 },
      objeto: { atraso: 1.20, dur: 0.80, dy: 34,  escala: 1,    mola: false, cascata: 0.14 },
      texto:  { atraso: 1.60, dur: 0.70, dy: 22,  escala: 1,    mola: false, cascata: 0.18 },
    },
  },

  lettering: {
    nome: 'Lettering',
    revela: 'lettering',
    passo: 0.075,         // intervalo entre LETRAS: precisa de respiro para ler solta
    zoomBase: 1.05,
    saida: { dur: 0.58, cascata: 0.07, dy:  72, escala: 0.80, gira: 9 },
    por: {
      base:   { atraso: 0.00, dur: 1.10, dy: 0,   escala: 1.10, mola: false, cascata: 0 },
      scrim:  { atraso: 0.50, dur: 0.80, dy: 0,   escala: 1,    mola: false, cascata: 0 },
      marca:  { atraso: 0.90, dur: 0.70, dy: -10, escala: 1,    mola: false, cascata: 0 },
      objeto: { atraso: 0.95, dur: 0.80, dy: 34,  escala: 1,    mola: false, cascata: 0.14 },
      // letra a letra demora: a frase mais longa leva ~1,5s sozinha, então o bloco
      // de texto precisa começar cedo para caber nos 5 segundos com sobra.
      texto:  { atraso: 0.95, dur: 0.70, dy: 22,  escala: 1,    mola: false, cascata: 0.14 },
    },
  },
};
