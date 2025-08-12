import os
import re
import json

import requests

S2_API_KEY = os.getenv('S2_API_KEY')
result_limit = 10


def main():
    find_basis_paper(query="venue:Nature artificial intelligenc")


def find_basis_paper(query):
    papers = None
    while not papers:
        if not query:
            continue

        # 包含所有可用字段
        fields = 'paperId,title,abstract,venue,year,referenceCount,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,authors,fieldsOfStudy,url,externalIds,tldr,publicationTypes,publicationDate,journal'
        sub_fields =  'paperId,title,abstract,venue,year,referenceCount,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,url,externalIds,tldr,publicationTypes,publicationDate,journal'
        rsp = requests.get('https://api.semanticscholar.org/graph/v1/paper/search',
                           headers={'X-API-KEY': S2_API_KEY},
                           params={'query': query, 'limit': result_limit, 'fields': sub_fields})
        rsp.raise_for_status()
        results = rsp.json()
        total = results["total"]
        if not total:
            print('No matches found. Please try another query.')
            continue

        print(f'Found {total} results. Showing up to {result_limit}.')
        papers = results['data']
        print_papers(papers)



def print_papers(papers):
    for idx, paper in enumerate(papers):
        print(f"\n{idx}. 论文JSON数据:")
        print(json.dumps(paper, ensure_ascii=False, indent=4))


if __name__ == '__main__':
    main()
"""
返回
{
    "paperId": "7b6a8c6d44e0f77bf930484e438d77b7465a69fb",
    "externalIds": {
        "DOI": "10.2139/ssrn.4337484",
        "CorpusId": 256347543
    },
    "url": "https://www.semanticscholar.org/paper/7b6a8c6d44e0f77bf930484e438d77b7465a69fb", 
    "title": "Education in the Era of Generative Artificial Intelligence (AI): Understanding the Potential Benefits of ChatGPT in Promoting Teaching and Learning",
    "venue": "Social Science Research Network",
    "year": 2023,
    "referenceCount": 32,
    "citationCount": 1619,
    "influentialCitationCount": 42,
    "isOpenAccess": false,
    "openAccessPdf": {
        "url": "",
        "status": null,
        "license": null,
        "disclaimer": "Notice: Paper or abstract available at https://api.unpaywall.org/v2/10.2139/ssrn.4337484?email=<INSERT_YOUR_EMAIL> or https://doi.org/10.2139/ssrn.4337484, which is subject to the license by the author or copyright owner provided with this content. Please go to the source to verify the license and copyright information for your use."
    },
    "fieldsOfStudy": null,
    "tldr": {
        "model": "tldr@v2.0.0",
        "text": "This is an exploratory study that synthesizes recent extant literature to offer some potential benefits and drawbacks of ChatGPT in promoting teaching and learning and offers recommendations on how this evolving generative AI tools could be leveraged to maximize teaching andlearning."
    },
    "publicationTypes": [
        "JournalArticle"
    ],
    "publicationDate": "2023-12-31",
    "journal": {
        "name": "SSRN Electronic Journal"
    },
    "authors": [
        {
            "authorId": "1411783122",
            "name": "David Baidoo-Anu"
        },
        {
            "authorId": "2203232571",
            "name": "Leticia Owusu Ansah"
        }
    ],
    "abstract": "Since its maiden release into the public domain on November 30, 2022, ChatGPT garnered more than one million subscribers within a week. The generative AI tool ⎼ChatGPT took the world by surprise with it sophisticated capacity to carry out remarkably complex tasks. The extraordinary abilities of ChatGPT to perform complex tasks within the field of education has caused mixed feelings among educators, as this advancement in AI seems to revolutionize existing educational praxis. This is an exploratory study that synthesizes recent extant literature to offer some potential benefits and drawbacks of ChatGPT in promoting teaching and learning. Benefits of ChatGPT include but are not limited to promotion of personalized and interactive learning, generating prompts for formative assessment activities that provide ongoing feedback to inform teaching and learning etc. The paper also highlights some inherent limitations in the ChatGPT such as generating wrong information, biases in data training, which may augment existing biases, privacy issues etc. The study offers recommendations on how ChatGPT could be leveraged to maximize teaching and learning. Policy makers, researchers, educators and technology experts could work together and start conversations on how these evolving generative AI tools could be used safely and constructively to improve education and support students’ learning."
}
"""