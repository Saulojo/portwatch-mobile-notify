# Rodando no Google Apps Script (grátis, sem PC ligado)

Usa a sua conta Google. O Google roda o `Code.gs` a cada 5 minutos e manda a mensagem no
Telegram quando a % do líder muda.

## Passo a passo (~5 minutos)

1. Abra https://script.google.com e clique em **Novo projeto**.
2. Clique em "Projeto sem título", no alto, e dê um nome (ex.: `PortWatch Telegram`).
3. Apague tudo o que estiver no editor (`function myFunction() {...}`) e cole o conteúdo
   inteiro do arquivo `Code.gs` desta pasta.
4. No topo do código, preencha com os mesmos valores do seu `config.json`:
   ```js
   const TELEGRAM_BOT_TOKEN = 'o token do bot';
   const TELEGRAM_CHAT_ID = 'o seu chat_id';
   ```
5. Salve (ícone de disquete ou `Ctrl + S`).
6. Na barra de cima, escolha a função **`instalarGatilho`** na lista e clique em **Executar**.
7. O Google pede autorização na primeira vez:
   - Clique em **Revisar permissões** e escolha a sua conta.
   - Vai aparecer "O Google não verificou este app". Isso é normal para scripts seus.
     Clique em **Avançado** → **Acessar PortWatch Telegram (não seguro)**.
   - Clique em **Permitir**. O script pede para acessar serviços externos (o site e o
     Telegram) e para rodar sozinho (o gatilho).
8. Pronto: chega no Telegram a mensagem "monitoramento iniciado" com o status atual.

Para conferir, clique no ícone de **relógio (Acionadores)** na barra da esquerda: deve aparecer
`verificar` com "Baseado no tempo". O ícone **Execuções** mostra cada checagem.

## Funções úteis (escolha na lista e clique em Executar)

| Função | O que faz |
|---|---|
| `testar` | manda o status atual agora |
| `instalarGatilho` | (re)cria o gatilho e já faz uma checagem |
| `removerGatilho` | para o monitor |

No topo do código também dá para mudar `INTERVALO_MINUTOS` (1, 5, 10, 15 ou 30) e
`AVISAR_QUANDO_SO_FPS_MUDA`. Depois de mudar o intervalo, rode `instalarGatilho` de novo.

## Atualizar o código

1. No editor, copie as duas linhas `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` para não perdê-las.
2. Apague tudo, cole o novo `Code.gs` e coloque as duas linhas de volta.
3. Salve. O gatilho continua o mesmo; não precisa rodar `instalarGatilho` de novo.

## Observações

- Resumo, "o que funciona" e "o que está travando" vêm em inglês do site e são traduzidos
  pelo Google Tradutor (`TRADUZIR_PARA_PORTUGUES`). Se a tradução falhar, vão em inglês.

- Se o site ficar fora do ar, o script só registra o erro e tenta de novo na próxima execução.
- Se o Telegram recusar a mensagem (token ou chat_id errado), a execução falha e o Google
  manda um e-mail de aviso.
- Depois de configurar aqui, não rode o `iniciar.bat` no PC, senão chegam mensagens repetidas.
