<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <style type="text/css">
      body {
        margin: 0;
        padding: 0;
        background: #f8f9fa;
        font-family: Helvetica, Arial, sans-serif;
        color: #111827;
      }
      table {
        border-spacing: 0;
        border-collapse: collapse;
      }
      .container {
        width: 100%;
        max-width: 920px;
        margin: 0 auto;
      }
      .card {
        width: 100%;
        border: 1px solid #dee2e6;
        border-top: 5px solid #dc2626;
        border-radius: 4px;
        background: #ffffff;
        overflow: hidden;
      }
      .card-body {
        padding: 20px;
      }
      .title {
        text-align: center;
        margin: 0;
        font-size: 20px;
        line-height: 24px;
      }
      .table {
        width: 100%;
      }
      .table th,
      .table td {
        border-top: 1px solid #e9ecef;
        padding: 12px;
        text-align: left;
        vertical-align: top;
        font-size: 14px;
        line-height: 20px;
      }
      .table th {
        font-weight: 700;
      }
      .quantidade {
        width: 1%;
        text-align: center;
        font-size: 20px;
        font-weight: 700;
      }
      .text-right {
        text-align: right;
      }
      .desc-col {
        text-align: right;
      }
      .spacer-16 {
        height: 16px;
      }
      .spacer-24 {
        height: 24px;
      }
      .row-alt {
        background: #f2f2f2;
      }
      .muted {
        color: #636c72;
        text-align: center;
        font-size: 13px;
      }
      .muted a {
        color: #636c72;
        text-decoration: none;
      }
    </style>
  </head>
  <body>
    <div style="display: none; max-height: 0; overflow: hidden">
      Pedido de almoço | Data {{ diaDeHoje }}
    </div>

    <table width="100%">
      <tr>
        <td align="center" style="padding: 0 16px">
          <table class="container">
            <tr>
              <td>
                <table align="center">
                  <tr>
                    <td style="padding-top: 24px">
                      <img
                        width="200"
                        src="https://garten.com.br/assets/img/logo.png"
                        alt="Garten"
                        style="height: auto; border: 0; outline: none"
                      />
                    </td>
                  </tr>
                </table>

                <div class="spacer-16"></div>
                <h2 class="title">Pedido de almoço | Data {{ diaDeHoje }}</h2>
                <div class="spacer-16"></div>

                <table class="card">
                  <tr>
                    <td>
                      <div class="card-body">
                        <h3 class="title"><strong>Pedidos</strong></h3>
                        <table class="table">
                          <thead>
                            <tr>
                              <th>Qtde</th>
                              <th class="desc-col" align="right" style="text-align: right">Descrição</th>
                            </tr>
                          </thead>
                          <tbody>
                            {% for pedido in resumo %}
                            <tr class="row-alt">
                              <td class="quantidade">{{ pedido["quantidade"] }}</td>
                              <td class="desc-col" align="right" style="text-align: right"><b>COMPLETO</b></td>
                            </tr>
                            {% endfor %}
                            <tr>
                              <td colspan="2" class="text-right">
                                <b>Total de pedidos</b> {{ pedidos|length }}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                </table>

                <div class="spacer-24"></div>

                <table class="card">
                  <tr>
                    <td>
                      <div class="card-body">
                        <h3 class="title"><strong>Lista detalhada</strong></h3>
                        <table class="table">
                          <thead>
                            <tr>
                              <th>Data</th>
                              <th>Usuário</th>
                              <th class="desc-col" align="right" style="text-align: right">Descrição</th>
                            </tr>
                          </thead>
                          <tbody>
                            {% for pedido in pedidos %}
                            <tr class="row-alt">
                              <td>{{ pedido["data"].split("T")[-1].split(".")[0] if "T" in pedido["data"] else pedido["data"][-8:] }}</td>
                              <td>{{ pedido["usuario"] }}</td>
                              <td class="desc-col" align="right" style="text-align: right"><b>COMPLETO</b></td>
                            </tr>
                            {% endfor %}
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                </table>

                <div class="spacer-24"></div>

                <div class="muted">
                  <a href="https://garten.com.br">Garten Automação</a> @ {{ anoAtual }}
                </div>

                <div class="spacer-24"></div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
