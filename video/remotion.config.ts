import { Config } from "@remotion/cli/config";

// Uma aba só. Com mais de uma, cada aba mede a fonte por conta e o texto
// alterna de posição entre quadros — o tremor custou cinco hipóteses erradas
// até a medição mostrar 0,447px de diferença entre abas paralelas.
Config.setConcurrency(1);
Config.setVideoImageFormat("jpeg");
// veio da experiência do Studio: sem o angle o Chrome do Remotion trava no Mac
Config.setChromiumOpenGlRenderer("angle");
Config.setCodec("h264");
Config.setCrf(18);
