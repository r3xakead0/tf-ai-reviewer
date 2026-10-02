# Scripts

Este directorio contiene utilidades para procesar planes de Terraform.

## `filter_plan.py`

El script `filter_plan.py` reduce un plan JSON de Terraform a los cambios relevantes para una revisión. Elimina los recursos cuya acción es `no-op` y conserva la dirección, el tipo, el nombre, las acciones y los valores anteriores y posteriores de cada recurso modificado.

### Requisitos

- Python 3
- Terraform, únicamente si se necesita generar o actualizar el plan de entrada

Actualmente, `filter_plan.py` solo utiliza módulos incluidos con Python, por lo que no requiere instalar las dependencias de `requirements.txt`.

### Ejecución

Desde la raíz del repositorio:

```bash
cd /Users/afu.tse/Documents/tf-ai-reviewer
python3 scripts/filter_plan.py terraform/plan.json terraform/filtered.json
```

El resultado se guardará en:

```text
terraform/filtered.json
```

La sintaxis general es:

```text
python3 scripts/filter_plan.py <plan_entrada.json> <archivo_salida.json>
```

Si no se proporcionan argumentos, el script busca `plan.json` en el directorio actual y genera `filtered.json` en ese mismo directorio:

```bash
python3 scripts/filter_plan.py
```

### Generar nuevamente el plan de Terraform

Desde la raíz del repositorio:

```bash
cd terraform
terraform init
terraform plan -out=tfplan
terraform show -json tfplan > plan.json

cd ..
python3 scripts/filter_plan.py terraform/plan.json terraform/filtered.json
```

### Seguridad

El archivo filtrado conserva los valores `before` y `after` del plan. Estos campos pueden incluir datos sensibles, por lo que `filtered.json` no debe compartirse ni añadirse al control de versiones sin revisarlo previamente.
