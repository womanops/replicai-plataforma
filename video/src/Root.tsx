import React from "react";
import { registerRoot, Composition } from "remotion";
import { Peca, type PecaProps } from "./peca/Peca";

// A peça não tem tamanho fixo: ele sai do formato que a plataforma adaptou.
// Por isso `calculateMetadata` — sem ele todo vídeo sairia no tamanho padrão.
const vazia: PecaProps = { base: "peca", canvas: { w: 1080, h: 1350 }, elementos: [] };

const Raiz: React.FC = () => (
  <Composition
    id="Peca"
    component={Peca}
    fps={30}
    defaultProps={vazia}
    durationInFrames={150}
    width={1080}
    height={1350}
    calculateMetadata={({ props }) => ({
      width: props.canvas?.w ?? 1080,
      height: props.canvas?.h ?? 1350,
      durationInFrames: Math.round((props.segundos ?? 5) * 30),
    })}
  />
);

registerRoot(Raiz);
