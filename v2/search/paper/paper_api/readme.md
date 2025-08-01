
## openalex 返回
```python
"""

"""
```
## paperlist 返回
## pubtator3 返回

```python

"""
1.根据摘要内关键词进行搜索:
https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/?text=abstract:"machine learning"&page=1
https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/?text=abstract:"deep learning" AND abstract:"medical imaging"&page=1
返回:
{
    "results": [
        {
            "_id": "33305538",
            "pmid": 33305538,
            "pmcid": "PMC7856512",
            "title": "A review on medical imaging synthesis using deep learning and its clinical applications",
            "journal": "J Appl Clin Med Phys",
            "authors": [
                "Wang T",
                "Lei Y",
                "Fu Y",
                "Wynne JF",
                "Curran WJ",
                "Liu T",
                "Yang X"
            ],
            "date": "2021-01-01T00:00:00Z",
            "doi": "10.1002/acm2.13121",
            "meta_date_publication": "2021 Jan",
            "meta_volume": "22",
            "meta_issue": "1",
            "meta_pages": "11-36",
            "score": 328.00574,
            "text_hl": "A review on <m>medical imaging</m> synthesis using <m>deep learning</m> and its clinical applications",
            "citations": {
                "NLM": "Wang T, Lei Y, Fu Y, Wynne JF, Curran WJ, Liu T, Yang X. A review on medical imaging synthesis using deep learning and its clinical applications J Appl Clin Med Phys. 2021 Jan;22(1):11-36. PMID: 33305538",
                "BibTeX": "@article{33305538, title={A review on medical imaging synthesis using deep learning and its clinical applications}, author={Wang T and Lei Y and Fu Y and Wynne JF and Curran WJ and Liu T and Yang X}, journal={J Appl Clin Med Phys}, volume={22}, number={1}, pages={11-36}}"
            }
        },
        {
            "_id": "40442267",
            "pmid": 40442267,
            "title": "Gaussian random fields as an abstract representation of patient metadata for multimodal medical image segmentation.",
            "journal": "Sci Rep",
            "authors": [
                "Cassidy B",
                "McBride C",
                "Kendrick C",
                "Reeves ND",
                "Pappachan JM",
                "Raad S",
                "Yap MH"
            ],
            "date": "2025-05-29T00:00:00Z",
            "doi": "10.1038/s41598-025-03393-x",
            "meta_date_publication": "2025 May 29",
            "meta_volume": "15",
            "meta_issue": "1",
            "meta_pages": "18810",
            "score": 327.17548,
            "text_hl": "Gaussian random fields as an <m>abstract</m> representation of @SPECIES_9606 @@@patient@@@ metadata for multimodal <m>medical image</m> segmentation.",
            "citations": {
                "NLM": "Cassidy B, McBride C, Kendrick C, Reeves ND, Pappachan JM, Raad S, Yap MH. Gaussian random fields as an abstract representation of patient metadata for multimodal medical image segmentation. Sci Rep. 2025 May 29;15(1):18810. PMID: 40442267",
                "BibTeX": "@article{40442267, title={Gaussian random fields as an abstract representation of patient metadata for multimodal medical image segmentation.}, author={Cassidy B and McBride C and Kendrick C and Reeves ND and Pappachan JM and Raad S and Yap MH}, journal={Sci Rep}, volume={15}, number={1}, pages={18810}}"
            }
        },
        {
            "_id": "38438821",
            "pmid": 38438821,
            "pmcid": "PMC10912073",
            "title": "Shallow and deep learning classifiers in medical image analysis",
            "journal": "Eur Radiol Exp",
            "authors": [
                "Prinzi F",
                "Currieri T",
                "Gaglio S",
                "Vitabile S"
            ],
            "date": "2024-03-05T00:00:00Z",
            "doi": "10.1186/s41747-024-00428-2",
            "meta_date_publication": "2024 Mar 5",
            "meta_volume": "8",
            "meta_issue": "1",
            "meta_pages": "26",
            "score": 325.22656,
            "text_hl": "Shallow and <m>deep learning</m> classifiers in <m>medical image</m> analysis",
            "citations": {
                "NLM": "Prinzi F, Currieri T, Gaglio S, Vitabile S. Shallow and deep learning classifiers in medical image analysis Eur Radiol Exp. 2024 Mar 5;8(1):26. PMID: 38438821",
                "BibTeX": "@article{38438821, title={Shallow and deep learning classifiers in medical image analysis}, author={Prinzi F and Currieri T and Gaglio S and Vitabile S}, journal={Eur Radiol Exp}, volume={8}, number={1}, pages={26}}"
            }
        },
        {
            "_id": "33521639",
            "pmid": 33521639,
            "pmcid": "PMC7829473",
            "title": "Deep learning for medical image analysis: a brief introduction",
            "journal": "Neurooncol Adv",
            "authors": [
                "Wiestler B",
                "Menze B"
            ],
            "date": "2021-01-23T00:00:00Z",
            "doi": "10.1093/noajnl/vdaa092",
            "meta_date_publication": "2020 Dec",
            "meta_volume": "2",
            "meta_issue": "Suppl 4",
            "meta_pages": "iv35-iv41",
            "score": 324.81958,
            "text_hl": "<m>Deep learning</m> for <m>medical image</m> analysis: a brief introduction",
            "citations": {
                "NLM": "Wiestler B, Menze B. Deep learning for medical image analysis: a brief introduction Neurooncol Adv. 2020 Dec;2(Suppl 4):iv35-iv41. PMID: 33521639",
                "BibTeX": "@article{33521639, title={Deep learning for medical image analysis: a brief introduction}, author={Wiestler B and Menze B}, journal={Neurooncol Adv}, volume={2}, number={Suppl 4}, pages={iv35-iv41}}"
            }
        },
        {
            "_id": "35474999",
            "pmid": 35474999,
            "pmcid": "PMC9017181",
            "title": "A deep-learning toolkit for visualization and interpretation of segmented medical images",
            "journal": "Cell Rep Methods",
            "authors": [
                "Ghosal S",
                "Shah P"
            ],
            "date": "2021-11-08T00:00:00Z",
            "doi": "10.1016/j.crmeth.2021.100107",
            "meta_date_publication": "2021 Nov 22",
            "meta_volume": "1",
            "meta_issue": "7",
            "meta_pages": "100107",
            "score": 320.60742,
            "text_hl": "A <m>deep-learning</m> toolkit for visualization and interpretation of segmented <m>medical images</m>",
            "citations": {
                "NLM": "Ghosal S, Shah P. A deep-learning toolkit for visualization and interpretation of segmented medical images Cell Rep Methods. 2021 Nov 22;1(7):100107. PMID: 35474999",
                "BibTeX": "@article{35474999, title={A deep-learning toolkit for visualization and interpretation of segmented medical images}, author={Ghosal S and Shah P}, journal={Cell Rep Methods}, volume={1}, number={7}, pages={100107}}"
            }
        },
        {
            "_id": "37426615",
            "pmid": 37426615,
            "pmcid": "PMC10329279",
            "title": "Medical imaging in rheumatoid arthritis: A review on deep learning approach",
            "journal": "Open Life Sci",
            "authors": [
                "Parashar A",
                "Rishi R",
                "Parashar A",
                "Rida I"
            ],
            "date": "2023-07-06T00:00:00Z",
            "doi": "10.1515/biol-2022-0611",
            "meta_date_publication": "2023",
            "meta_volume": "18",
            "meta_issue": "1",
            "meta_pages": "20220611",
            "score": 317.60242,
            "text_hl": "<m>Medical imaging</m> in @DISEASE_Arthritis_Rheumatoid @DISEASE_MESH:D001172 @@@rheumatoid arthritis@@@: A review on <m>deep learning</m> approach",
            "citations": {
                "NLM": "Parashar A, Rishi R, Parashar A, Rida I. Medical imaging in rheumatoid arthritis: A review on deep learning approach Open Life Sci. 2023;18(1):20220611. PMID: 37426615",
                "BibTeX": "@article{37426615, title={Medical imaging in rheumatoid arthritis: A review on deep learning approach}, author={Parashar A and Rishi R and Parashar A and Rida I}, journal={Open Life Sci}, volume={18}, number={1}, pages={20220611}}"
            }
        },
        {
            "_id": "32906819",
            "pmid": 32906819,
            "pmcid": "PMC7570704",
            "title": "3D Deep Learning on Medical Images: A Review",
            "journal": "Sensors (Basel)",
            "authors": [
                "Singh SP",
                "Wang L",
                "Gupta S",
                "Goli H",
                "Padmanabhan P",
                "Gulyás B"
            ],
            "date": "2020-09-07T00:00:00Z",
            "doi": "10.3390/s20185097",
            "meta_date_publication": "2020 Sep 7",
            "meta_volume": "20",
            "meta_issue": "18",
            "meta_pages": "",
            "score": 317.56158,
            "text_hl": "3D <m>Deep Learning</m> on <m>Medical Images</m>: A Review",
            "citations": {
                "NLM": "Singh SP, Wang L, Gupta S, Goli H, Padmanabhan P, Gulyás B. 3D Deep Learning on Medical Images: A Review Sensors (Basel). 2020 Sep 7;20(18):. PMID: 32906819",
                "BibTeX": "@article{32906819, title={3D Deep Learning on Medical Images: A Review}, author={Singh SP and Wang L and Gupta S and Goli H and Padmanabhan P and Gulyás B}, journal={Sensors (Basel)}, volume={20}, number={18}}"
            }
        },
        {
            "_id": "39775630",
            "pmid": 39775630,
            "pmcid": "PMC11929708",
            "title": "Sparse keypoint segmentation of lung fissures: efficient geometric deep learning for abstracting volumetric images",
            "journal": "Int J Comput Assist Radiol Surg",
            "authors": [
                "Kaftan P",
                "Heinrich MP",
                "Hansen L",
                "Rasche V",
                "Kestler HA",
                "Bigalke A"
            ],
            "date": "2025-01-07T00:00:00Z",
            "doi": "10.1007/s11548-024-03310-z",
            "meta_date_publication": "2025 Jan 7",
            "meta_volume": "",
            "meta_issue": "",
            "meta_pages": "",
            "score": 317.54065,
            "text_hl": "Sparse keypoint segmentation of lung fissures: efficient geometric <m>deep learning</m> for <m>abstracting</m> volumetric images",
            "citations": {
                "NLM": "Kaftan P, Heinrich MP, Hansen L, Rasche V, Kestler HA, Bigalke A. Sparse keypoint segmentation of lung fissures: efficient geometric deep learning for abstracting volumetric images Int J Comput Assist Radiol Surg. 2025 Jan 7;():. PMID: 39775630",
                "BibTeX": "@article{39775630, title={Sparse keypoint segmentation of lung fissures: efficient geometric deep learning for abstracting volumetric images}, author={Kaftan P and Heinrich MP and Hansen L and Rasche V and Kestler HA and Bigalke A}, journal={Int J Comput Assist Radiol Surg}}"
            }
        },
        {
            "_id": "37177747",
            "pmid": 37177747,
            "pmcid": "PMC10181656",
            "title": "Saliency Map and Deep Learning in Binary Classification of Brain Tumours",
            "journal": "Sensors (Basel)",
            "authors": [
                "Chmiel W",
                "Kwiecień J",
                "Motyka K"
            ],
            "date": "2023-05-07T00:00:00Z",
            "doi": "10.3390/s23094543",
            "meta_date_publication": "2023 May 7",
            "meta_volume": "23",
            "meta_issue": "9",
            "meta_pages": "",
            "score": 316.27673,
            "text_hl": "We have presented the basic issues related to <m>deep learning</m> techniques. A significant challenge in using <m>deep learning</m> methods is the ability to explain the decision-making process of the network. ",
            "citations": {
                "NLM": "Chmiel W, Kwiecień J, Motyka K. Saliency Map and Deep Learning in Binary Classification of Brain Tumours Sensors (Basel). 2023 May 7;23(9):. PMID: 37177747",
                "BibTeX": "@article{37177747, title={Saliency Map and Deep Learning in Binary Classification of Brain Tumours}, author={Chmiel W and Kwiecień J and Motyka K}, journal={Sensors (Basel)}, volume={23}, number={9}}"
            }
        },
        {
            "_id": "34188157",
            "pmid": 34188157,
            "pmcid": "PMC8242021",
            "title": "Medical imaging deep learning with differential privacy",
            "journal": "Sci Rep",
            "authors": [
                "Ziller A",
                "Usynin D",
                "Braren R",
                "Makowski M",
                "Rueckert D",
                "Kaissis G"
            ],
            "date": "2021-06-29T00:00:00Z",
            "doi": "10.1038/s41598-021-93030-0",
            "meta_date_publication": "2021 Jun 29",
            "meta_volume": "11",
            "meta_issue": "1",
            "meta_pages": "13524",
            "score": 315.89136,
            "text_hl": "<m>Medical imaging</m> <m>deep learning</m> with differential privacy",
            "citations": {
                "NLM": "Ziller A, Usynin D, Braren R, Makowski M, Rueckert D, Kaissis G. Medical imaging deep learning with differential privacy Sci Rep. 2021 Jun 29;11(1):13524. PMID: 34188157",
                "BibTeX": "@article{34188157, title={Medical imaging deep learning with differential privacy}, author={Ziller A and Usynin D and Braren R and Makowski M and Rueckert D and Kaissis G}, journal={Sci Rep}, volume={11}, number={1}, pages={13524}}"
            }
        }
    ],
    "facets": {
        "facet_queries": {},
        "facet_fields": {
            "journal": [
                {
                    "name": "Cancers (Basel)",
                    "type": "int",
                    "value": 441
                },
                {
                    "name": "Sci Rep",
                    "type": "int",
                    "value": 179
                },
                {
                    "name": "Diagnostics (Basel)",
                    "type": "int",
                    "value": 169
                },
                {
                    "name": "PLoS One",
                    "type": "int",
                    "value": 163
                },
                {
                    "name": "Sensors (Basel)",
                    "type": "int",
                    "value": 157
                }
            ],
            "type": [
                {
                    "name": "Journal Article",
                    "type": "int",
                    "value": 5426
                },
                {
                    "name": "Review",
                    "type": "int",
                    "value": 1582
                },
                {
                    "name": "Meta-Analysis",
                    "type": "int",
                    "value": 79
                },
                {
                    "name": "Multicenter Study",
                    "type": "int",
                    "value": 43
                },
                {
                    "name": "Editorial",
                    "type": "int",
                    "value": 17
                }
            ],
            "year": [
                {
                    "name": "2023",
                    "type": "int",
                    "value": 1315
                },
                {
                    "name": "2022",
                    "type": "int",
                    "value": 1190
                },
                {
                    "name": "2024",
                    "type": "int",
                    "value": 1179
                },
                {
                    "name": "2021",
                    "type": "int",
                    "value": 761
                },
                {
                    "name": "2025",
                    "type": "int",
                    "value": 495
                },
                {
                    "name": "2020",
                    "type": "int",
                    "value": 354
                },
                {
                    "name": "2019",
                    "type": "int",
                    "value": 148
                },
                {
                    "name": "2018",
                    "type": "int",
                    "value": 60
                },
                {
                    "name": "2017",
                    "type": "int",
                    "value": 17
                },
                {
                    "name": "2016",
                    "type": "int",
                    "value": 6
                },
                {
                    "name": "1978",
                    "type": "int",
                    "value": 1
                },
                {
                    "name": "2014",
                    "type": "int",
                    "value": 1
                },
                {
                    "name": "2015",
                    "type": "int",
                    "value": 1
                }
            ]
        },
        "facet_ranges": {},
        "facet_intervals": {},
        "facet_heatmaps": {}
    },
    "page_size": 10,
    "current": 1,
    "count": 5528,
    "total_pages": 553
}

"""
"""
2.获取摘要或全文
"""
```