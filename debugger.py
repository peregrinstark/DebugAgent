import IPython
import os
from openai import OpenAI

# Your raw Python code
with open('debugger_api.py', 'rt') as fp:
    python_code = fp.read()

def generate_code(client, user_request):
    prompt = f"""
    Given the following Python code:

    ```python
    {python_code}
    ```

    User Request: "{user_request}"

    Generate the corresponding Python code, by assuming a global variable of
    type `Debugger` with the name `gdb`. Assume each object can print itself
    via the __str__ method. When user is asking to recursively descend into
    variables, take note that the recursion always terminates in a basic
    variable.

    The user can refer to variables using a Python attribute and index syntax.
    Some examples are below:

    - "var1.member1[10].member2" should be interpreted as a request for
      var1.member("member1").index(10).member("member2")
    - "var1.member1.member2[5]" should be interpreted as a request for
      var1.member("member1").member("member2").index(5)

    Return pure python code without annotations or delimiters. If the user
    command cannot be understood or satisfied using the provided API, then
    generate python code that raises a RuntimeError exception with an
    appropriate user error message.
    """
    response = client.chat.completions.create( 
            model="gpt-4o",
            messages=[ 
                {
                    "role": "system", 
                    "content": "You are a helpful code generator."
                }, 
                { "role": "user", 
                  "content": prompt
                } 
            ], max_tokens=500)
    print(response.choices[0].message.content)

# Example user request
user_request = "Load and print the variable called dlfe_globals from the target DLFE_IUSS"
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
IPython.embed()

